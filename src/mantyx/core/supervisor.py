"""
Process supervisor for perpetual (long-running) applications.

Manages starting, stopping, and monitoring of app processes.
"""

import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from mantyx.config import get_settings
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_app_log_path, get_logger
from mantyx.models.app import App, AppState
from mantyx.models.execution import Execution, ExecutionStatus

logger = get_logger("supervisor")


class ProcessSupervisor:
    """Supervises perpetual app processes."""

    def __init__(self):
        self.settings = get_settings()
        self.venv_manager = VenvManager()
        self._processes: dict[int, subprocess.Popen] = {}

    def _get_app_dir(self, app_name: str) -> Path:
        """Get the app's directory."""
        return self.settings.apps_dir / app_name / "app"

    def start_app(self, app: App) -> Execution:
        """Start a perpetual app."""
        if app.state == AppState.RUNNING:
            raise RuntimeError(f"App {app.name} is already running")

        logger.info(f"Starting app: {app.name}", app_id=app.id)

        # Create execution record
        execution = Execution(
            app_id=app.id,
            status=ExecutionStatus.PENDING,
            trigger_type="manual",
        )

        with get_db() as session:
            session.add(execution)
            session.flush()
            execution_id = execution.id

        try:
            # Get paths
            app_dir = self._get_app_dir(app.name)
            entrypoint = app_dir / app.entrypoint

            if not entrypoint.exists():
                raise RuntimeError(f"Entrypoint not found: {entrypoint}")

            # Get Python executable
            python_exe = self.venv_manager.get_python_executable(app.name)
            if not python_exe.exists():
                raise RuntimeError(f"Virtual environment not found for {app.name}")

            # Prepare log files
            stdout_path, stderr_path = get_app_log_path(app.name, execution_id)

            # Prepare environment
            env = os.environ.copy()
            if app.environment:
                env.update(app.environment)

            # Start process
            with open(stdout_path, "w") as stdout_file, open(stderr_path, "w") as stderr_file:
                process = subprocess.Popen(
                    [str(python_exe), str(entrypoint)],
                    cwd=str(app_dir),
                    env=env,
                    stdout=stdout_file,
                    stderr=stderr_file,
                    start_new_session=True,
                )

            # Update execution and app
            with get_db() as session:
                exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
                if exec_obj:
                    exec_obj.status = ExecutionStatus.RUNNING
                    exec_obj.started_at = datetime.now()
                    exec_obj.pid = process.pid
                    exec_obj.stdout_path = str(stdout_path)
                    exec_obj.stderr_path = str(stderr_path)

                app_obj = session.query(App).filter(App.id == app.id).first()
                if app_obj:
                    app_obj.state = AppState.RUNNING
                    app_obj.pid = process.pid

            self._processes[app.id] = process

            logger.info(
                f"App {app.name} started with PID {process.pid}",
                app_id=app.id,
                execution_id=execution_id,
            )

            return execution

        except Exception as e:
            logger.error(f"Failed to start app {app.name}: {e}", app_id=app.id)

            # Update execution status
            with get_db() as session:
                exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
                if exec_obj:
                    exec_obj.status = ExecutionStatus.FAILED
                    exec_obj.ended_at = datetime.now()
                    exec_obj.error_message = str(e)

                app_obj = session.query(App).filter(App.id == app.id).first()
                if app_obj:
                    app_obj.state = AppState.FAILED
                    app_obj.last_error = str(e)
                    app_obj.last_error_at = datetime.now()

            raise

    def stop_app(self, app: App, timeout: int = 10) -> None:
        """Stop a running app."""
        if app.state != AppState.RUNNING or not app.pid:
            logger.warning(f"App {app.name} is not running", app_id=app.id)
            return

        logger.info(f"Stopping app: {app.name} (PID: {app.pid})", app_id=app.id)

        try:
            # Try to get the process
            try:
                process = psutil.Process(app.pid)
            except psutil.NoSuchProcess:
                logger.warning(f"Process {app.pid} not found for app {app.name}", app_id=app.id)
                self._mark_stopped(app)
                return

            # Try graceful shutdown first
            process.terminate()

            # Wait for process to exit
            try:
                process.wait(timeout=timeout)
                logger.info(f"App {app.name} stopped gracefully", app_id=app.id)
            except psutil.TimeoutExpired:
                # Force kill if graceful shutdown fails
                logger.warning(f"Forcefully killing app {app.name}", app_id=app.id)
                process.kill()
                process.wait(timeout=5)

            self._mark_stopped(app)

        except Exception as e:
            logger.error(f"Error stopping app {app.name}: {e}", app_id=app.id)
            raise

    def _mark_stopped(self, app: App) -> None:
        """Mark an app as stopped in the database."""
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app.id).first()
            if app_obj:
                app_obj.state = AppState.STOPPED
                app_obj.pid = None

            # Find active execution and mark as completed
            execution = (
                session.query(Execution)
                .filter(
                    Execution.app_id == app.id,
                    Execution.status == ExecutionStatus.RUNNING,
                )
                .first()
            )
            if execution:
                execution.status = ExecutionStatus.SUCCESS
                execution.ended_at = datetime.now()

        # Remove from tracked processes
        if app.id in self._processes:
            del self._processes[app.id]

    def restart_app(self, app: App) -> Execution:
        """Restart an app."""
        logger.info(f"Restarting app: {app.name}", app_id=app.id)

        if app.state == AppState.RUNNING:
            self.stop_app(app)

        # Wait a moment before restarting
        time.sleep(1)

        # Increment restart count
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app.id).first()
            if app_obj:
                app_obj.restart_count += 1
                app_obj.last_restart_at = datetime.now()

        return self.start_app(app)

    def check_app_running(self, app: App) -> bool:
        """Check if an app is actually running."""
        if not app.pid:
            return False

        try:
            process = psutil.Process(app.pid)
            return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return False

    def monitor_apps(self) -> None:
        """Monitor all running apps and handle failures."""
        with get_db() as session:
            running_apps = (
                session.query(App)
                .filter(
                    App.state == AppState.RUNNING,
                    App.is_deleted == False,
                )
                .all()
            )

            for app in running_apps:
                if not self.check_app_running(app):
                    logger.warning(
                        f"App {app.name} is marked running but process not found",
                        app_id=app.id,
                    )

                    # Check if we should restart
                    if self._should_restart(app):
                        try:
                            logger.info(f"Auto-restarting app {app.name}", app_id=app.id)
                            self.restart_app(app)
                        except Exception as e:
                            logger.error(
                                f"Failed to auto-restart app {app.name}: {e}",
                                app_id=app.id,
                            )
                            # Mark as failed
                            app.state = AppState.FAILED
                            app.last_error = str(e)
                            app.last_error_at = datetime.now()
                            session.add(app)
                    else:
                        # Mark as failed
                        logger.error(
                            f"App {app.name} exceeded max restarts",
                            app_id=app.id,
                        )
                        app.state = AppState.FAILED
                        app.last_error = "Exceeded maximum restart attempts"
                        app.last_error_at = datetime.now()
                        session.add(app)

    def _should_restart(self, app: App) -> bool:
        """Determine if an app should be restarted based on restart policy."""
        if app.restart_policy == "never":
            return False

        if app.restart_policy == "always":
            return True

        if app.restart_policy == "on-failure":
            # Check restart count within time window
            if app.last_restart_at:
                window = timedelta(seconds=self.settings.restart_window)
                if datetime.now() - app.last_restart_at > window:
                    # Reset count if outside window
                    app.restart_count = 0

            return app.restart_count < app.max_restarts

        return False

    def cleanup(self) -> None:
        """Stop all tracked processes on shutdown."""
        logger.info("Cleaning up supervisor processes")

        for app_id, process in list(self._processes.items()):
            try:
                if process.poll() is None:  # Still running
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        process.kill()
            except Exception as e:
                logger.error(f"Error cleaning up process for app {app_id}: {e}")
