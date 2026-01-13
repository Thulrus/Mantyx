"""
Scheduler for running scheduled applications.

Uses APScheduler to manage cron and interval-based job execution.
"""

import traceback
from datetime import datetime
from typing import Optional

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


class AppScheduler:
    """Manages scheduled execution of applications."""
    
    def __init__(self):
        self.settings = get_settings()
        self.venv_manager = VenvManager()
        self._scheduler: Optional[BackgroundScheduler] = None
    
    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler and self._scheduler.running:
            logger.warning("Scheduler is already running")
            return
        
        logger.info("Starting scheduler")
        
        jobstores = {
            'default': SQLAlchemyJobStore(url=self.settings.effective_database_url)
        }
        
        executors = {
            'default': ThreadPoolExecutor(max_workers=10)
        }
        
        job_defaults = {
            'coalesce': True,
            'max_instances': 1,
            'misfire_grace_time': 60,
        }
        
        self._scheduler = BackgroundScheduler(
            jobstores=jobstores,
            executors=executors,
            job_defaults=job_defaults,
        )
        
        # Load existing schedules
        self._load_schedules()
        
        self._scheduler.start()
        logger.info("Scheduler started")
    
    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler and self._scheduler.running:
            logger.info("Stopping scheduler")
            self._scheduler.shutdown(wait=True)
            logger.info("Scheduler stopped")
    
    def _load_schedules(self) -> None:
        """Load all enabled schedules from database."""
        with get_db() as session:
            schedules = session.query(Schedule).filter(
                Schedule.is_enabled == True
            ).all()
            
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
        
        # Remove existing job if present
        if self._scheduler.get_job(job_id):
            self._scheduler.remove_job(job_id)
        
        # Determine trigger
        if schedule.schedule_type == "cron":
            if not schedule.cron_expression:
                raise ValueError("Cron expression required for cron schedule")
            trigger = CronTrigger.from_crontab(
                schedule.cron_expression,
                timezone=schedule.timezone,
            )
        elif schedule.schedule_type == "interval":
            if not schedule.interval_seconds:
                raise ValueError("Interval required for interval schedule")
            trigger = IntervalTrigger(
                seconds=schedule.interval_seconds,
                timezone=schedule.timezone,
            )
        else:
            raise ValueError(f"Unknown schedule type: {schedule.schedule_type}")
        
        # Add job
        self._scheduler.add_job(
            func=self._execute_scheduled_app,
            trigger=trigger,
            id=job_id,
            name=f"{schedule.app.name} - {schedule.name}",
            args=[schedule.app_id, schedule.id],
            coalesce=schedule.coalesce,
            misfire_grace_time=schedule.misfire_grace_time,
        )
        
        logger.info(
            f"Added schedule {schedule.name} for app {schedule.app.name}",
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
    
    def _execute_scheduled_app(self, app_id: int, schedule_id: int) -> None:
        """Execute a scheduled app."""
        import subprocess
        
        logger.info(
            f"Executing scheduled app: app_id={app_id}, schedule_id={schedule_id}"
        )
        
        # Create execution record
        execution = Execution(
            app_id=app_id,
            status=ExecutionStatus.PENDING,
            trigger_type="scheduled",
            trigger_details=f"schedule_id={schedule_id}",
        )
        
        with get_db() as session:
            session.add(execution)
            session.flush()
            execution_id = execution.id
        
        try:
            # Get app and schedule
            with get_db() as session:
                app = session.query(App).filter(App.id == app_id).first()
                schedule = session.query(Schedule).filter(Schedule.id == schedule_id).first()
                
                if not app:
                    raise RuntimeError(f"App {app_id} not found")
                
                if not schedule:
                    raise RuntimeError(f"Schedule {schedule_id} not found")
                
                if app.state not in (AppState.ENABLED, AppState.STOPPED):
                    raise RuntimeError(f"App {app.name} is not enabled")
                
                if app.app_type != AppType.SCHEDULED:
                    raise RuntimeError(f"App {app.name} is not a scheduled app")
            
            # Get paths
            app_dir = self.settings.apps_dir / app.name / "app"
            entrypoint = app_dir / app.entrypoint
            
            if not entrypoint.exists():
                raise RuntimeError(f"Entrypoint not found: {entrypoint}")
            
            # Get Python executable
            python_exe = self.venv_manager.get_python_executable(app.name)
            if not python_exe.exists():
                raise RuntimeError(f"Virtual environment not found for {app.name}")
            
            # Prepare log files
            stdout_path, stderr_path = get_app_log_path(app.name, execution_id)
            
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
            if app.environment:
                env.update(app.environment)
            
            # Execute
            with open(stdout_path, "w") as stdout_file, open(stderr_path, "w") as stderr_file:
                result = subprocess.run(
                    [str(python_exe), str(entrypoint)],
                    cwd=str(app_dir),
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    timeout=schedule.timeout_seconds if schedule.timeout_seconds else None,
                )
            
            # Update execution status
            with get_db() as session:
                exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
                if exec_obj:
                    exec_obj.status = (
                        ExecutionStatus.SUCCESS if result.returncode == 0
                        else ExecutionStatus.FAILED
                    )
                    exec_obj.ended_at = datetime.now()
                    exec_obj.exit_code = result.returncode
                
                # Update schedule last run
                sched_obj = session.query(Schedule).filter(Schedule.id == schedule_id).first()
                if sched_obj:
                    sched_obj.last_run = datetime.now()
                    sched_obj.run_count += 1
            
            if result.returncode == 0:
                logger.info(
                    f"Scheduled app {app.name} completed successfully",
                    app_id=app_id,
                    execution_id=execution_id,
                )
            else:
                logger.error(
                    f"Scheduled app {app.name} failed with exit code {result.returncode}",
                    app_id=app_id,
                    execution_id=execution_id,
                )
        
        except subprocess.TimeoutExpired:
            logger.error(
                f"Scheduled app execution timed out",
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
