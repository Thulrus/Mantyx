"""
Scheduler for running scheduled applications.

Uses APScheduler to manage cron and interval-based job execution. The
database's schedules table is the single source of truth: jobs are kept in
memory and rebuilt from it at startup, so a deleted or disabled schedule can
never linger as a stale persisted job.
"""

import os
import signal
import subprocess
import threading
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from mantyx.config import get_settings, get_system_timezone
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_app_log_path, get_logger
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.schedule import Schedule
from mantyx.models.setting import Setting

logger = get_logger("scheduler")

# How often crashed perpetual apps are detected (seconds).
MONITOR_INTERVAL_SECONDS = 5
# How often git-based apps are checked for new commits (seconds).
GIT_CHECK_INTERVAL_SECONDS = 30 * 60
# Run states from which a *scheduled* trigger may fire. Manual runs are allowed
# from any installed state.
SCHEDULE_ACTIVE_STATES = (AppState.ENABLED, AppState.STOPPED)
MANUAL_RUN_STATES = (
    AppState.ENABLED,
    AppState.STOPPED,
    AppState.INSTALLED,
    AppState.DISABLED,
    AppState.FAILED,
)


class RunInProgressError(RuntimeError):
    """Raised when a scheduled app is asked to run while a run is already going."""


# ── In-flight scheduled runs ────────────────────────────────────────────────
# execution_id -> {"app_id": int, "process": Popen | None, "cancelled": bool}
_runs: dict[int, dict] = {}
_runs_lock = threading.Lock()
# app ids with a run being prepared or in progress (guards against overlap
# before the subprocess exists).
_busy_apps: set[int] = set()


def is_app_run_in_progress(app_id: int) -> bool:
    with _runs_lock:
        return app_id in _busy_apps


def cancel_execution(execution_id: int) -> bool:
    """Stop an in-progress scheduled run. Returns False if it isn't running here."""
    with _runs_lock:
        run = _runs.get(execution_id)
        if not run:
            return False
        run["cancelled"] = True
        process = run.get("process")
    if process is not None:
        _kill_group(process)
    return True


def _kill_group(process: subprocess.Popen) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass


def stop_all_runs() -> None:
    """Cancel every in-progress scheduled run (used when Mantyx shuts down)."""
    with _runs_lock:
        ids = list(_runs.keys())
    for execution_id in ids:
        cancel_execution(execution_id)


def get_effective_timezone() -> str:
    """The timezone schedules run in: the Settings value, else the system's."""
    try:
        with get_db() as session:
            setting = session.query(Setting).filter(Setting.key == "timezone").first()
            if setting and setting.value:
                ZoneInfo(setting.value)
                return setting.value
    except Exception:
        pass
    return get_system_timezone()


def build_trigger(
    schedule_type: str,
    cron_expression: str | None,
    interval_seconds: int | None,
    timezone: str,
):
    """Build an APScheduler trigger, raising ValueError with a readable message if invalid."""
    tz = ZoneInfo(timezone)
    if schedule_type == "cron":
        if not cron_expression or not cron_expression.strip():
            raise ValueError("A cron expression is required")
        parts = cron_expression.split()
        if len(parts) != 5:
            raise ValueError("A cron expression needs 5 fields: minute hour day month day-of-week")
        minute, hour, day, month, day_of_week = parts
        try:
            return CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                timezone=tz,
            )
        except ValueError as e:
            raise ValueError(f"Invalid cron expression: {e}") from e
    if schedule_type == "interval":
        if not interval_seconds or interval_seconds < 1:
            raise ValueError("Interval must be at least 1 second")
        return IntervalTrigger(seconds=interval_seconds, timezone=tz)
    raise ValueError(f"Unknown schedule type: {schedule_type}")


def preview_fire_times(trigger, count: int = 3) -> list[datetime]:
    """The next `count` times a trigger would fire, starting now."""
    times: list[datetime] = []
    previous = None
    now = datetime.now(trigger.timezone)
    for _ in range(count):
        nxt = trigger.get_next_fire_time(
            previous, previous + timedelta(seconds=1) if previous else now
        )
        if nxt is None:
            break
        times.append(nxt)
        previous = nxt
    return times


def _remove_job_quietly(schedule_id: int) -> None:
    from mantyx.core import runtime

    scheduler = runtime.get_scheduler()
    if scheduler is not None:
        scheduler.remove_schedule(schedule_id)


def execute_scheduled_app(app_id: int, schedule_id: int | None) -> None:
    """Execute a scheduled app.

    schedule_id is None for "Run now". Scheduled triggers for apps that are
    paused, not installed or deleted are skipped silently (no failed run is
    recorded); a run is never started while the previous one is still going.

    Raises RunInProgressError for a manual run that would overlap.
    """
    from mantyx.core import runtime

    is_manual = schedule_id is None
    trigger_type = "manual" if is_manual else "scheduled"
    if runtime.is_shutting_down():
        return

    settings = get_settings()
    venv_manager = VenvManager()

    with get_db() as session:
        app = session.query(App).filter(App.id == app_id).first()
        if not app or app.is_deleted:
            if not is_manual:
                _remove_job_quietly(schedule_id)
            return
        if app.app_type != AppType.SCHEDULED:
            if is_manual:
                raise RuntimeError(f"App {app.name} is not a scheduled app")
            return
        app_name = app.name
        app_entrypoint = app.entrypoint
        app_environment = app.environment
        app_state = app.state

        schedule_name = None
        timeout_seconds = None
        if not is_manual:
            schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
            if not schedule or not schedule.is_enabled:
                _remove_job_quietly(schedule_id)
                return
            schedule_name = schedule.name
            timeout_seconds = schedule.timeout_seconds or None

    if is_manual:
        if app_state not in MANUAL_RUN_STATES:
            raise RuntimeError(f"App {app_name} can't run in state {app_state.value}")
    elif app_state not in SCHEDULE_ACTIVE_STATES:
        # Paused or not yet installed/activated: skip without recording a failure.
        return

    with _runs_lock:
        if app_id in _busy_apps:
            busy = True
        else:
            busy = False
            _busy_apps.add(app_id)
    if busy:
        if is_manual:
            raise RunInProgressError(f"{app_name} is already running")
        logger.warning(
            f"Skipped scheduled run of {app_name}: the previous run is still in progress",
            app_id=app_id,
        )
        return

    execution_id: int | None = None
    try:
        execution = Execution(
            app_id=app_id,
            status=ExecutionStatus.PENDING,
            trigger_type=trigger_type,
            trigger_details=(f"schedule: {schedule_name}" if schedule_name else "Run now"),
        )
        with get_db() as session:
            session.add(execution)
            session.flush()
            execution_id = execution.id

        with _runs_lock:
            _runs[execution_id] = {"app_id": app_id, "process": None, "cancelled": False}

        _run_execution(
            execution_id=execution_id,
            app_id=app_id,
            app_name=app_name,
            app_entrypoint=app_entrypoint,
            app_environment=app_environment,
            timeout_seconds=timeout_seconds,
            schedule_id=schedule_id,
            settings=settings,
            venv_manager=venv_manager,
        )
    finally:
        with _runs_lock:
            _busy_apps.discard(app_id)
            if execution_id is not None:
                _runs.pop(execution_id, None)


def _run_execution(
    *,
    execution_id: int,
    app_id: int,
    app_name: str,
    app_entrypoint: str,
    app_environment: dict | None,
    timeout_seconds: int | None,
    schedule_id: int | None,
    settings,
    venv_manager: VenvManager,
) -> None:
    from mantyx.core.supervisor import build_app_env

    def finish(status: ExecutionStatus, exit_code: int | None = None, error: str | None = None):
        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = status
                exec_obj.ended_at = datetime.now()
                exec_obj.exit_code = exit_code
                if error:
                    exec_obj.error_message = error
            if schedule_id is not None:
                sched_obj = session.query(Schedule).filter(Schedule.id == schedule_id).first()
                if sched_obj:
                    sched_obj.last_run = datetime.now()
                    sched_obj.run_count = (sched_obj.run_count or 0) + 1

    try:
        app_dir = settings.apps_dir / app_name / "app"
        entrypoint = app_dir / app_entrypoint
        if not entrypoint.exists():
            raise RuntimeError(f"Entrypoint not found: {app_entrypoint}")

        python_exe = venv_manager.get_python_executable(app_name)
        if not python_exe.exists():
            logger.info(f"Virtual environment missing for {app_name}, rebuilding...", app_id=app_id)
            requirements_file = app_dir / "requirements.txt"
            venv_manager.install_requirements(
                app_name,
                requirements_file if requirements_file.exists() else None,
            )

        stdout_path, stderr_path = get_app_log_path(app_name, execution_id)
        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = ExecutionStatus.RUNNING
                exec_obj.started_at = datetime.now()
                exec_obj.stdout_path = str(stdout_path)
                exec_obj.stderr_path = str(stderr_path)

        env = build_app_env(app_name, app_environment)

        with open(stdout_path, "a") as stdout_file, open(stderr_path, "a") as stderr_file:
            process = subprocess.Popen(
                [str(python_exe), str(entrypoint)],
                cwd=str(app_dir),
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )

        with _runs_lock:
            run = _runs.get(execution_id)
            if run is not None:
                run["process"] = process
            cancelled_early = bool(run and run["cancelled"])
        if cancelled_early:
            _kill_group(process)

        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.pid = process.pid

        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            _kill_group(process)
            logger.error(
                f"{app_name} timed out after {timeout_seconds}s and was stopped",
                app_id=app_id,
                execution_id=execution_id,
            )
            finish(
                ExecutionStatus.TIMEOUT,
                error=f"Timed out after {timeout_seconds} seconds and was stopped",
            )
            return

        with _runs_lock:
            cancelled = bool(_runs.get(execution_id, {}).get("cancelled"))

        if cancelled:
            logger.info(
                f"Run of {app_name} was cancelled", app_id=app_id, execution_id=execution_id
            )
            finish(ExecutionStatus.CANCELLED, exit_code=returncode, error="Cancelled by user")
        elif returncode == 0:
            logger.info(
                f"{app_name} finished successfully", app_id=app_id, execution_id=execution_id
            )
            finish(ExecutionStatus.SUCCESS, exit_code=0)
        else:
            logger.error(
                f"{app_name} failed with exit code {returncode}",
                app_id=app_id,
                execution_id=execution_id,
            )
            finish(
                ExecutionStatus.FAILED,
                exit_code=returncode,
                error=f"Exited with code {returncode}",
            )

    except Exception as e:
        logger.error(
            f"Run of {app_name} failed: {e}",
            app_id=app_id,
            execution_id=execution_id,
            details=traceback.format_exc(),
        )
        finish(ExecutionStatus.FAILED, error=str(e))


def monitor_perpetual_apps() -> None:
    """Detect and recover crashed perpetual apps (called on a fixed interval by the scheduler)."""
    from mantyx.core import maintenance, runtime

    try:
        runtime.get_supervisor().monitor_apps()
    except Exception as e:
        logger.error(f"Unhandled error in perpetual-app monitor: {e}")
    try:
        maintenance.rotate_running_logs()
    except Exception as e:
        logger.error(f"Log rotation failed: {e}")


def run_maintenance() -> None:
    from mantyx.core import maintenance

    maintenance.run_retention()


def check_git_updates() -> None:
    """Background check of every git-based app for new commits (results are cached)."""
    from mantyx.core import runtime

    with get_db() as session:
        app_ids = [
            row[0]
            for row in session.query(App.id)
            .filter(App.git_url.isnot(None), App.is_deleted == False)  # noqa: E712
            .all()
        ]
    manager = runtime.get_app_manager()
    for app_id in app_ids:
        try:
            manager.check_git_update(app_id)
        except Exception:
            pass  # recorded in the cache by check_git_update


class AppScheduler:
    """Manages scheduled execution of applications."""

    def __init__(self):
        self.settings = get_settings()
        self.venv_manager = VenvManager()
        self._scheduler: BackgroundScheduler | None = None
        self.timezone: str = get_system_timezone()

    @property
    def running(self) -> bool:
        return bool(self._scheduler and self._scheduler.running)

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler and self._scheduler.running:
            logger.warning("Scheduler is already running")
            return

        self.timezone = get_effective_timezone()
        logger.info(f"Starting scheduler (timezone: {self.timezone})")

        self._scheduler = BackgroundScheduler(
            jobstores={"default": MemoryJobStore()},
            executors={"default": ThreadPoolExecutor(max_workers=20)},
            job_defaults={"coalesce": True, "max_instances": 1, "misfire_grace_time": 60},
            timezone=ZoneInfo(self.timezone),
        )

        self._scheduler.start()
        self._load_schedules()

        self._scheduler.add_job(
            func=monitor_perpetual_apps,
            trigger=IntervalTrigger(seconds=MONITOR_INTERVAL_SECONDS),
            id="__mantyx_monitor__",
            name="Mantyx: watch always-running apps",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=MONITOR_INTERVAL_SECONDS * 2,
        )
        self._scheduler.add_job(
            func=run_maintenance,
            trigger=IntervalTrigger(hours=6),
            next_run_time=datetime.now(ZoneInfo(self.timezone)) + timedelta(minutes=10),
            id="__mantyx_maintenance__",
            name="Mantyx: clean up old runs, logs and backups",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        self._scheduler.add_job(
            func=check_git_updates,
            trigger=IntervalTrigger(seconds=GIT_CHECK_INTERVAL_SECONDS),
            next_run_time=datetime.now(ZoneInfo(self.timezone)) + timedelta(seconds=30),
            id="__mantyx_git_check__",
            name="Mantyx: check Git apps for updates",
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=3600,
        )
        logger.info(f"Scheduler started with {len(self._scheduler.get_jobs())} jobs")

    def stop(self) -> None:
        """Stop the scheduler and any scheduled runs in progress."""
        if self._scheduler and self._scheduler.running:
            logger.info("Stopping scheduler")
            self._scheduler.shutdown(wait=False)
        stop_all_runs()

    def _load_schedules(self) -> None:
        """Load all enabled schedules of live scheduled apps from the database."""
        with get_db() as session:
            schedules = (
                session.query(Schedule)
                .join(App, App.id == Schedule.app_id)
                .filter(
                    Schedule.is_enabled == True,  # noqa: E712
                    App.is_deleted == False,  # noqa: E712
                    App.app_type == AppType.SCHEDULED,
                )
                .all()
            )

            for schedule in schedules:
                try:
                    self.add_schedule(schedule)
                except Exception as e:
                    logger.error(
                        f"Failed to load schedule '{schedule.name}': {e}",
                        app_id=schedule.app_id,
                    )

    def add_schedule(self, schedule: Schedule) -> None:
        """Add (or replace) a schedule's job."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not started")

        trigger = build_trigger(
            schedule.schedule_type,
            schedule.cron_expression,
            schedule.interval_seconds,
            self.timezone,
        )
        self._scheduler.add_job(
            func=execute_scheduled_app,
            trigger=trigger,
            id=f"schedule_{schedule.id}",
            name=f"{schedule.app.name} - {schedule.name}",
            args=[schedule.app_id, schedule.id],
            coalesce=True if schedule.coalesce is None else schedule.coalesce,
            misfire_grace_time=schedule.misfire_grace_time or 60,
            replace_existing=True,
        )

    def remove_schedule(self, schedule_id: int) -> None:
        """Remove a schedule from the scheduler."""
        if not self._scheduler:
            return

        job_id = f"schedule_{schedule_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info(f"Removed schedule {schedule_id}")

    def remove_app_schedules(self, schedule_ids: list[int]) -> None:
        for schedule_id in schedule_ids:
            self.remove_schedule(schedule_id)

    def next_run_time(self, schedule_id: int) -> datetime | None:
        if not self._scheduler:
            return None
        job = self._scheduler.get_job(f"schedule_{schedule_id}")
        return getattr(job, "next_run_time", None) if job else None

    def set_timezone(self, timezone: str) -> None:
        """Switch the scheduling timezone and rebuild every schedule's trigger."""
        ZoneInfo(timezone)
        self.timezone = timezone
        if not self._scheduler:
            return
        for job in self._scheduler.get_jobs():
            if job.id.startswith("schedule_"):
                self._scheduler.remove_job(job.id)
        self._load_schedules()
        logger.info(f"Scheduler timezone changed to {timezone}")

    def pause_schedule(self, schedule_id: int) -> None:
        """Pause a schedule."""
        if not self._scheduler:
            return
        job = self._scheduler.get_job(f"schedule_{schedule_id}")
        if job:
            job.pause()

    def resume_schedule(self, schedule_id: int) -> None:
        """Resume a paused schedule."""
        if not self._scheduler:
            return
        job = self._scheduler.get_job(f"schedule_{schedule_id}")
        if job:
            job.resume()

    def get_scheduler_status(self) -> dict:
        """Get detailed scheduler status for diagnostics."""
        if not self._scheduler:
            return {"running": False, "error": "Scheduler not initialized"}

        tz = ZoneInfo(self.timezone)
        jobs_info = []
        for job in self._scheduler.get_jobs():
            next_run = getattr(job, "next_run_time", None)
            jobs_info.append(
                {
                    "id": job.id,
                    "name": job.name,
                    "next_run_time": next_run.isoformat() if next_run else None,
                    "next_run_time_local": (
                        next_run.astimezone(tz).isoformat() if next_run else None
                    ),
                    "trigger": str(job.trigger),
                }
            )

        return {
            "running": self._scheduler.running,
            "num_jobs": len(jobs_info),
            "jobs": jobs_info,
            "scheduler_timezone": self.timezone,
            "current_time": datetime.now(tz).isoformat(),
        }
