"""
Tests for scheduling: trigger building, timezone handling, and how scheduled
runs behave (skipping paused apps, never overlapping, recording results).
"""

import os
import sys
import threading
import time
from datetime import datetime
from unittest.mock import MagicMock

import pytest

import mantyx.config as config_module
import mantyx.database as database_module
from mantyx.config import init_settings
from mantyx.core import runtime
from mantyx.core.scheduler import (
    AppScheduler,
    build_trigger,
    cancel_execution,
    execute_scheduled_app,
    get_effective_timezone,
    is_app_run_in_progress,
    preview_fire_times,
)
from mantyx.database import get_db, init_db
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.schedule import Schedule
from mantyx.models.setting import Setting


@pytest.fixture
def instance(tmp_path):
    settings = init_settings(base_dir=tmp_path / "mantyx_base", database_url=None)
    settings.ensure_directories()
    init_db()
    yield settings
    scheduler = runtime.get_scheduler()
    if scheduler:
        scheduler.stop()
    runtime.clear_runtime()
    database_module.dispose_engine()
    config_module._settings = None


def _make_app(settings, name="job", state=AppState.ENABLED, script="print('hi')\n"):
    source = settings.apps_dir / name / "app"
    source.mkdir(parents=True)
    (source / "main.py").write_text(script)
    # Fake venv: point bin/python at the interpreter running the tests.
    venv_bin = settings.venvs_dir / name / "bin"
    venv_bin.mkdir(parents=True)
    os.symlink(sys.executable, venv_bin / "python")
    with get_db() as session:
        app = App(
            name=name,
            display_name=name,
            app_type=AppType.SCHEDULED,
            state=state,
            entrypoint="main.py",
        )
        session.add(app)
        session.flush()
        return app.id


def _executions(app_id):
    with get_db() as session:
        rows = session.query(Execution).filter(Execution.app_id == app_id).all()
        session.expunge_all()
        return rows


# ── triggers ────────────────────────────────────────────────────────────────


def test_weekday_names_fire_on_the_named_days():
    """The UI writes day names, which mean the same thing in every cron dialect."""
    trigger = build_trigger("cron", "0 7 * * mon,wed,fri", None, "UTC")
    days = {t.strftime("%a") for t in preview_fire_times(trigger, 6)}
    assert days == {"Mon", "Wed", "Fri"}


def test_invalid_cron_is_rejected_with_readable_message():
    with pytest.raises(ValueError, match="5 fields"):
        build_trigger("cron", "0 7 * *", None, "UTC")
    with pytest.raises(ValueError, match="Invalid cron"):
        build_trigger("cron", "99 7 * * *", None, "UTC")
    with pytest.raises(ValueError, match="at least 1 second"):
        build_trigger("interval", None, 0, "UTC")


def test_cron_runs_in_the_configured_timezone():
    trigger = build_trigger("cron", "0 7 * * *", None, "America/New_York")
    nxt = preview_fire_times(trigger, 1)[0]
    assert nxt.hour == 7
    assert str(nxt.tzinfo) == "America/New_York"


def test_effective_timezone_uses_the_setting(instance):
    with get_db() as session:
        session.add(Setting(key="timezone", value="Asia/Tokyo"))
    assert get_effective_timezone() == "Asia/Tokyo"


def test_timezone_change_retimes_existing_schedules(instance):
    app_id = _make_app(instance)
    with get_db() as session:
        session.add(
            Schedule(app_id=app_id, name="daily", schedule_type="cron", cron_expression="0 7 * * *")
        )
    scheduler = AppScheduler()
    scheduler.start()
    runtime.set_runtime(scheduler=scheduler)
    with get_db() as session:
        session.flush()
        schedule_id = session.query(Schedule.id).scalar()

    scheduler.set_timezone("Asia/Tokyo")

    nxt = scheduler.next_run_time(schedule_id)
    assert nxt.hour == 7 and str(nxt.tzinfo) == "Asia/Tokyo"


def test_schedules_of_deleted_apps_are_not_loaded(instance):
    app_id = _make_app(instance)
    with get_db() as session:
        session.add(
            Schedule(app_id=app_id, name="daily", schedule_type="cron", cron_expression="0 7 * * *")
        )
        session.query(App).filter(App.id == app_id).first().is_deleted = True
    scheduler = AppScheduler()
    scheduler.start()
    runtime.set_runtime(scheduler=scheduler)
    assert not [j for j in scheduler._scheduler.get_jobs() if j.id.startswith("schedule_")]


# ── runs ────────────────────────────────────────────────────────────────────


def test_scheduled_trigger_for_paused_app_is_skipped_without_a_failed_run(instance):
    app_id = _make_app(instance, state=AppState.DISABLED)
    with get_db() as session:
        session.add(
            Schedule(app_id=app_id, name="s", schedule_type="interval", interval_seconds=60)
        )
        session.flush()
        schedule_id = session.query(Schedule.id).scalar()

    execute_scheduled_app(app_id, schedule_id)

    assert _executions(app_id) == []


def test_scheduled_trigger_for_missing_app_does_nothing(instance):
    execute_scheduled_app(12345, 1)  # must not raise


def test_manual_run_records_output_and_success(instance):
    app_id = _make_app(instance, state=AppState.INSTALLED, script="print('hello from job')\n")

    execute_scheduled_app(app_id, None)

    [run] = _executions(app_id)
    assert run.status == ExecutionStatus.SUCCESS
    assert run.exit_code == 0
    assert run.trigger_type == "manual"
    with open(run.stdout_path) as f:
        assert "hello from job" in f.read()


def test_failed_run_records_exit_code(instance):
    app_id = _make_app(instance, script="import sys; sys.exit(3)\n")
    execute_scheduled_app(app_id, None)
    [run] = _executions(app_id)
    assert run.status == ExecutionStatus.FAILED
    assert run.exit_code == 3


def test_runs_never_overlap_and_can_be_cancelled(instance):
    app_id = _make_app(instance, script="import time; time.sleep(30)\n")
    with get_db() as session:
        session.add(
            Schedule(app_id=app_id, name="s", schedule_type="interval", interval_seconds=60)
        )
        session.flush()
        schedule_id = session.query(Schedule.id).scalar()

    thread = threading.Thread(target=execute_scheduled_app, args=(app_id, None))
    thread.start()
    deadline = time.time() + 10
    while time.time() < deadline:
        runs = _executions(app_id)
        if runs and runs[0].pid:
            break
        time.sleep(0.05)
    assert is_app_run_in_progress(app_id)

    # A scheduled trigger while it's running is skipped, not queued or doubled.
    execute_scheduled_app(app_id, schedule_id)
    assert len(_executions(app_id)) == 1

    assert cancel_execution(_executions(app_id)[0].id)
    thread.join(timeout=15)
    assert not thread.is_alive()

    [run] = _executions(app_id)
    assert run.status == ExecutionStatus.CANCELLED
    assert not is_app_run_in_progress(app_id)


def test_timeout_stops_the_run_and_counts_the_schedule(instance):
    app_id = _make_app(instance, script="import time; time.sleep(30)\n")
    with get_db() as session:
        session.add(
            Schedule(
                app_id=app_id,
                name="s",
                schedule_type="interval",
                interval_seconds=60,
                timeout_seconds=1,
            )
        )
        session.flush()
        schedule_id = session.query(Schedule.id).scalar()

    started = datetime.now()
    execute_scheduled_app(app_id, schedule_id)
    assert (datetime.now() - started).total_seconds() < 15

    [run] = _executions(app_id)
    assert run.status == ExecutionStatus.TIMEOUT
    with get_db() as session:
        schedule = session.query(Schedule).first()
        assert schedule.run_count == 1 and schedule.last_run is not None


def test_startup_reconcile_closes_interrupted_scheduled_runs(instance):
    from mantyx.core.supervisor import ProcessSupervisor

    app_id = _make_app(instance)
    with get_db() as session:
        session.add(
            Execution(app_id=app_id, status=ExecutionStatus.RUNNING, trigger_type="scheduled")
        )

    ProcessSupervisor().reconcile_on_startup()

    [run] = _executions(app_id)
    assert run.status == ExecutionStatus.CANCELLED
    assert "restarted" in run.error_message


def test_monitor_job_uses_the_shared_supervisor(instance, monkeypatch):
    from mantyx.core import scheduler as scheduler_module

    shared = MagicMock()
    runtime.set_runtime(supervisor=shared)
    monkeypatch.setattr("mantyx.core.maintenance.rotate_running_logs", lambda: None)

    scheduler_module.monitor_perpetual_apps()

    shared.monitor_apps.assert_called_once()
