"""
User-facing status for apps.

The database `state` column mixes "what the user wants" (enabled/disabled)
with "what is happening" (running/failed). The UI shouldn't make people learn
that state machine, so this module turns it — plus live facts like an active
install, the latest run, or the next scheduled time — into one plain status:

    status        machine key used for styling/filtering
    status_label  short words for the badge ("Running", "Last run failed")
    attention     True when the user probably needs to do something

along with the raw facts the UI uses to write a one-line explanation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.schedule import Schedule


def _iso(dt: datetime | None) -> str | None:
    """ISO string with offset; naive values are the server's local time."""
    if dt is None:
        return None
    return (dt.astimezone() if dt.tzinfo is None else dt).isoformat()


def _execution_summary(execution: Execution | None) -> dict[str, Any] | None:
    if execution is None:
        return None
    return {
        "id": execution.id,
        "status": execution.status.value,
        "started_at": _iso(execution.started_at),
        "ended_at": _iso(execution.ended_at),
        "exit_code": execution.exit_code,
        "error_message": execution.error_message,
        "trigger_type": execution.trigger_type,
    }


def build_app_views(session: Session, apps: list[App]) -> list[dict[str, Any]]:
    """Status views for many apps using a fixed number of queries."""
    from mantyx.core import runtime
    from mantyx.core.app_manager import get_git_status
    from mantyx.core.scheduler import is_app_run_in_progress
    from mantyx.core.tasks import task_manager

    app_ids = [a.id for a in apps]
    if not app_ids:
        return []

    latest_ids = [
        row[0]
        for row in session.query(func.max(Execution.id))
        .filter(Execution.app_id.in_(app_ids))
        .group_by(Execution.app_id)
        .all()
    ]
    latest: dict[int, Execution] = {
        e.app_id: e for e in session.query(Execution).filter(Execution.id.in_(latest_ids)).all()
    }
    running_execs: dict[int, Execution] = {}
    for e in (
        session.query(Execution)
        .filter(Execution.app_id.in_(app_ids), Execution.status == ExecutionStatus.RUNNING)
        .order_by(Execution.id.asc())
        .all()
    ):
        running_execs[e.app_id] = e

    schedules: dict[int, list[Schedule]] = {}
    for s in session.query(Schedule).filter(Schedule.app_id.in_(app_ids)).all():
        schedules.setdefault(s.app_id, []).append(s)

    scheduler = runtime.get_scheduler()
    active_tasks = task_manager.active_by_app()

    views = []
    for app in apps:
        views.append(
            _build_view(
                app,
                latest=latest.get(app.id),
                running=running_execs.get(app.id),
                schedules=schedules.get(app.id, []),
                scheduler=scheduler,
                task=active_tasks.get(app.id),
                git=get_git_status(app.id) if app.git_url else None,
                run_in_progress=is_app_run_in_progress(app.id),
            )
        )
    return views


def _build_view(app, *, latest, running, schedules, scheduler, task, git, run_in_progress):
    enabled_schedules = [s for s in schedules if s.is_enabled]
    next_runs = []
    for s in enabled_schedules:
        nxt = scheduler.next_run_time(s.id) if scheduler else None
        if nxt:
            next_runs.append(nxt)
    next_run = min(next_runs) if next_runs else None

    view: dict[str, Any] = {
        "enabled": app.state not in (AppState.DISABLED, AppState.UPLOADED, AppState.DELETED),
        "next_run": _iso(next_run),
        "last_run": _execution_summary(latest),
        "current_run": _execution_summary(running),
        "schedule_count": len(schedules),
        "enabled_schedule_count": len(enabled_schedules),
        "active_task": {"id": task.id, "name": task.name} if task else None,
        "git_status": git,
        "update_available": bool(git and git.get("update_available")),
    }

    status, label, attention = _derive_status(
        app, latest, running, enabled_schedules, task, run_in_progress
    )
    view.update(status=status, status_label=label, attention=attention)
    return view


def _derive_status(app, latest, running, enabled_schedules, task, run_in_progress):
    if task is not None:
        return "working", task.name, False

    if app.state == AppState.DELETED:
        return "deleted", "Deleted", False
    if app.state == AppState.UPLOADED:
        return "not_installed", "Not installed", True

    if app.app_type == AppType.PERPETUAL:
        if app.state == AppState.RUNNING:
            return "running", "Running", False
        if app.state == AppState.FAILED:
            return "failed", "Failed", True
        if app.state == AppState.ENABLED:
            return "starting", "Starting", False
        return "stopped", "Stopped", False

    # Scheduled apps
    if run_in_progress or running is not None:
        return "running_now", "Running now", False
    if app.state in (AppState.DISABLED, AppState.INSTALLED):
        return "paused", "Paused", False
    if not enabled_schedules:
        return "no_schedule", "No schedule", True
    if latest is not None and latest.status in (ExecutionStatus.FAILED, ExecutionStatus.TIMEOUT):
        return "last_failed", "Last run failed", True
    return "scheduled", "Scheduled", False
