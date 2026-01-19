"""
Scheduler for running scheduled applications.

Uses APScheduler to manage cron and interval-based job execution.
"""

import traceback
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.executors.pool import ThreadPoolExecutor
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from mantyx.config import get_settings
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_app_log_path, get_logger
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.schedule import Schedule

logger = get_logger("scheduler")


def execute_scheduled_app(app_id: int, schedule_id: int | None) -> None:
    """Execute a scheduled app (standalone function for APScheduler serialization)."""
    import subprocess

    trigger_type = "manual" if schedule_id is None else "scheduled"
    trigger_details = f"schedule_id={schedule_id}" if schedule_id else "manual execution"

    logger.info(
        f"🎯 SCHEDULER TRIGGERED: Executing scheduled app: app_id={app_id}, schedule_id={schedule_id}, time={datetime.now()}"
    )

    settings = get_settings()
    venv_manager = VenvManager()

    # Create execution record
    execution = Execution(
        app_id=app_id,
        status=ExecutionStatus.PENDING,
        trigger_type=trigger_type,
        trigger_details=trigger_details,
    )

    with get_db() as session:
        session.add(execution)
        session.flush()
        execution_id = execution.id

    try:
        # Get app and schedule - extract all needed values in the session
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()

            if not app:
                raise RuntimeError(f"App {app_id} not found")

            if app.app_type != AppType.SCHEDULED:
                raise RuntimeError(f"App {app.name} is not a scheduled app")

            # Extract values we need outside the session
            app_name = app.name
            app_entrypoint = app.entrypoint
            app_environment = app.environment

            # For scheduled runs, validate schedule exists
            if schedule_id is not None:
                schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
                if not schedule:
                    raise RuntimeError(f"Schedule {schedule_id} not found")
                timeout_seconds = schedule.timeout_seconds if schedule.timeout_seconds else None
            else:
                # Manual run - no timeout by default
                timeout_seconds = None
                schedule = None

            # Check app state (allow more states for manual runs)
            if schedule_id is not None and app.state not in (AppState.ENABLED, AppState.STOPPED):
                raise RuntimeError(f"App {app_name} is not enabled")

        # Get paths
        app_dir = settings.apps_dir / app_name / "app"
        entrypoint = app_dir / app_entrypoint

        if not entrypoint.exists():
            raise RuntimeError(f"Entrypoint not found: {entrypoint}")

        # Get Python executable
        python_exe = venv_manager.get_python_executable(app_name)
        if not python_exe.exists():
            raise RuntimeError(f"Virtual environment not found for {app_name}")

        # Prepare log files
        stdout_path, stderr_path = get_app_log_path(app_name, execution_id)

        # Update execution status
        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = ExecutionStatus.RUNNING
                exec_obj.started_at = datetime.now()
                exec_obj.stdout_path = str(stdout_path)
                exec_obj.stderr_path = str(stderr_path)

        # Prepare environment
        import os

        env = os.environ.copy()
        if app_environment:
            env.update(app_environment)

        # Execute
        with open(stdout_path, "w") as stdout_file, open(stderr_path, "w") as stderr_file:
            result = subprocess.run(
                [str(python_exe), str(entrypoint)],
                cwd=str(app_dir),
                env=env,
                stdout=stdout_file,
                stderr=stderr_file,
                timeout=timeout_seconds,
            )

        # Update execution status
        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = (
                    ExecutionStatus.SUCCESS if result.returncode == 0 else ExecutionStatus.FAILED
                )
                exec_obj.ended_at = datetime.now()
                exec_obj.exit_code = result.returncode

            # Update schedule last run (only if this was a scheduled execution)
            if schedule_id is not None:
                sched_obj = session.query(Schedule).filter(Schedule.id == schedule_id).first()
                if sched_obj:
                    sched_obj.last_run = datetime.now()
                    sched_obj.run_count += 1

        if result.returncode == 0:
            logger.info(
                f"Scheduled app {app_name} completed successfully",
                app_id=app_id,
                execution_id=execution_id,
            )
        else:
            logger.error(
                f"Scheduled app {app_name} failed with exit code {result.returncode}",
                app_id=app_id,
                execution_id=execution_id,
            )

    except subprocess.TimeoutExpired:
        logger.error(
            "Scheduled app execution timed out",
            app_id=app_id,
            execution_id=execution_id,
        )

        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = ExecutionStatus.TIMEOUT
                exec_obj.ended_at = datetime.now()
                exec_obj.error_message = "Execution timed out"

    except Exception as e:
        logger.error(
            f"Scheduled app execution failed: {e}",
            app_id=app_id,
            execution_id=execution_id,
            details=traceback.format_exc(),
        )

        with get_db() as session:
            exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
            if exec_obj:
                exec_obj.status = ExecutionStatus.FAILED
                exec_obj.ended_at = datetime.now()
                exec_obj.error_message = str(e)


class AppScheduler:
    """Manages scheduled execution of applications."""

    def __init__(self):
        self.settings = get_settings()
        self.venv_manager = VenvManager()
        self._scheduler: BackgroundScheduler | None = None

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler and self._scheduler.running:
            logger.warning("Scheduler is already running")
            return

        logger.info("⚙️  Starting scheduler...")

        # Get system timezone
        from mantyx.config import get_system_timezone

        system_tz = get_system_timezone()
        logger.info(f"📍 Scheduler timezone: {system_tz}")

        jobstores = {"default": SQLAlchemyJobStore(url=self.settings.effective_database_url)}

        executors = {"default": ThreadPoolExecutor(max_workers=10)}

        job_defaults = {
            "coalesce": True,
            "max_instances": 1,
            "misfire_grace_time": 60,
        }

        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
            timezone=system_tz,
        )

        # Load existing schedules
        self._load_schedules()

        self._scheduler.start()
        logger.info("✅ Scheduler started successfully")
        logger.info(f"📅 Loaded {len(self._scheduler.get_jobs())} jobs")

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._scheduler.running:
            logger.info("Stopping scheduler")
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")

    def _load_schedules(self) -> None:
        """Load all enabled schedules from database."""
        with get_db() as session:
            schedules = session.query(Schedule).filter(Schedule.is_enabled == True).all()

            for schedule in schedules:
                try:
                    self.add_schedule(schedule)
                except Exception as e:
                    logger.error(
                        f"Failed to load schedule {schedule.id}: {e}",
                        app_id=schedule.app_id,
                    )

    def add_schedule(self, schedule: Schedule) -> None:
        """Add a schedule to the scheduler."""
        if not self._scheduler:
            raise RuntimeError("Scheduler not started")

        job_id = f"schedule_{schedule.id}"

        # Determine trigger
        if schedule.schedule_type == "cron":
            if not schedule.cron_expression:
                raise ValueError("Cron expression required for cron schedule")

            logger.info(
                f"Creating cron trigger: expression='{schedule.cron_expression}', timezone='{schedule.timezone}' (using scheduler timezone)",
                app_id=schedule.app_id,
            )

            # Parse cron expression (format: "minute hour day month day_of_week")
            # NOTE: Do NOT pass timezone to CronTrigger - it will use the scheduler's timezone
            # Passing timezone causes APScheduler to interpret the hour as UTC instead of local time
            parts = schedule.cron_expression.split()
            if len(parts) != 5:
                raise ValueError(f"Invalid cron expression: {schedule.cron_expression}")

            minute, hour, day, month, day_of_week = parts

            trigger = CronTrigger(
                minute=minute,
                hour=hour,
                day=day,
                month=month,
                day_of_week=day_of_week,
                # Don't set timezone here - inherit from scheduler
            )

            # Log the next run time for debugging
            tz = ZoneInfo(schedule.timezone)
            next_run = trigger.get_next_fire_time(None, datetime.now(tz))
            logger.info(
                f"Trigger created - Next run will be: {next_run}",
                app_id=schedule.app_id,
            )
        elif schedule.schedule_type == "interval":
            if not schedule.interval_seconds:
                raise ValueError("Interval required for interval schedule")

            logger.info(
                f"Creating interval trigger: seconds={schedule.interval_seconds}, timezone='{schedule.timezone}' (using scheduler timezone)",
                app_id=schedule.app_id,
            )

            trigger = IntervalTrigger(
                seconds=schedule.interval_seconds,
                # Don't set timezone here - inherit from scheduler
            )
        else:
            raise ValueError(f"Unknown schedule type: {schedule.schedule_type}")

        # Add job (replace if exists)
        self._scheduler.add_job(
            func=execute_scheduled_app,
            trigger=trigger,
            id=job_id,
            name=f"{schedule.app.name} - {schedule.name}",
            args=[schedule.app_id, schedule.id],
            coalesce=schedule.coalesce,
            misfire_grace_time=schedule.misfire_grace_time,
            replace_existing=True,
        )

        # Get next run time
        job = self._scheduler.get_job(job_id)
        next_run = job.next_run_time if job else None

        logger.info(
            f"Added schedule '{schedule.name}' for app '{schedule.app.name}' - Next run: {next_run}",
            app_id=schedule.app_id,
        )

    def remove_schedule(self, schedule_id: int) -> None:
        """Remove a schedule from the scheduler."""
        if not self._scheduler:
            return

        job_id = f"schedule_{schedule_id}"
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
            logger.info(f"Removed schedule {schedule_id}")

    def pause_schedule(self, schedule_id: int) -> None:
        """Pause a schedule."""
        if not self._scheduler:
            return

        job_id = f"schedule_{schedule_id}"
        job = self._scheduler.get_job(job_id)
        if job:
            job.pause()
            logger.info(f"Paused schedule {schedule_id}")

    def resume_schedule(self, schedule_id: int) -> None:
        """Resume a paused schedule."""
        if not self._scheduler:
            return

        job_id = f"schedule_{schedule_id}"
        job = self._scheduler.get_job(job_id)
        if job:
            job.resume()
            logger.info(f"Resumed schedule {schedule_id}")

    def get_scheduler_status(self) -> dict:
        """Get detailed scheduler status for debugging."""
        if not self._scheduler:
            return {"running": False, "error": "Scheduler not initialized"}

        from mantyx.config import get_system_timezone

        system_tz = get_system_timezone()
        tz = ZoneInfo(system_tz)
        current_time = datetime.now(tz)

        jobs_info = []
        for job in self._scheduler.get_jobs():
            # Get next run time and convert to local timezone if needed
            next_run = job.next_run_time
            next_run_local = None
            if next_run:
                # Ensure next_run has timezone info
                if next_run.tzinfo is None:
                    # If naive, assume it's in scheduler's timezone
                    next_run = next_run.replace(tzinfo=tz)
                next_run_local = next_run.astimezone(tz)

            job_info = {
                "id": job.id,
                "name": job.name,
                "next_run_time": next_run.isoformat() if next_run else None,
                "next_run_time_local": next_run_local.isoformat() if next_run_local else None,
                "trigger": str(job.trigger),
            }
            jobs_info.append(job_info)

        return {
            "running": self._scheduler.running,
            "num_jobs": len(jobs_info),
            "jobs": jobs_info,
            "scheduler_timezone": (
                str(self._scheduler.timezone) if hasattr(self._scheduler, "timezone") else "unknown"
            ),
            "current_time": current_time.isoformat(),
        }
