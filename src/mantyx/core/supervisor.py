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
        self._processes: dict[int, subprocess.Popen | psutil.Process] = {}

    def _get_app_dir(self, app_name: str) -> Path:
        """Get the app's directory."""
        return self.settings.apps_dir / app_name / "app"

    def start_app(self, app_id: int) -> Execution:
        """Start a perpetual app."""
        # Re-fetch the app from the DB and extract all needed scalar attributes now.
        # Callers must pass the integer app_id rather than an ORM App object, because
        # App objects may be expired+detached (session committed and closed by the caller)
        # and accessing ANY attribute on them — including the PK — raises
        # DetachedInstanceError when expire_on_commit=True.
        with get_db() as session:
            fresh = session.query(App).filter(App.id == app_id).first()
            if fresh is None:
                raise RuntimeError(f"App {app_id} not found")
            current_state = fresh.state
            app_name = fresh.name
            app_entrypoint = fresh.entrypoint
            app_environment = fresh.environment

        if current_state == AppState.RUNNING:
            raise RuntimeError(f"App {app_name} is already running")

        logger.info(f"Starting app: {app_name}", app_id=app_id)

        # Create execution record inside the try block so any DB error is caught,
        # logged, and the app state is rolled back rather than silently 500-ing.
        execution_id: int | None = None
        try:
            execution = Execution(
                app_id=app_id,
                status=ExecutionStatus.PENDING,
                trigger_type="manual",
            )
            with get_db() as session:
                session.add(execution)
                session.flush()
                execution_id = execution.id

            # Get paths
            app_dir = self._get_app_dir(app_name)
            entrypoint = app_dir / app_entrypoint

            if not entrypoint.exists():
                raise RuntimeError(f"Entrypoint not found: {entrypoint}")

            # Get Python executable
            python_exe = self.venv_manager.get_python_executable(app_name)
            if not python_exe.exists():
                raise RuntimeError(f"Virtual environment not found for {app_name}")

            # Prepare log files
            stdout_path, stderr_path = get_app_log_path(app_name, execution_id)

            # Prepare environment
            env = os.environ.copy()
            if app_environment:
                env.update(app_environment)

            # Inject persistent data directory so apps can store runtime data
            # that survives upgrades. Apps read: Path(os.environ["APP_DATA_DIR"])
            app_data_dir = self.settings.apps_dir / app_name / "data"
            app_data_dir.mkdir(parents=True, exist_ok=True)
            env["APP_DATA_DIR"] = str(app_data_dir)

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
            started_at = datetime.now()
            with get_db() as session:
                exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
                if exec_obj:
                    exec_obj.status = ExecutionStatus.RUNNING
                    exec_obj.started_at = started_at
                    exec_obj.pid = process.pid
                    exec_obj.stdout_path = str(stdout_path)
                    exec_obj.stderr_path = str(stderr_path)
                else:
                    logger.error(
                        f"Execution record {execution_id} not found after starting app {app_name}; returned state will be stale",
                        app_id=app_id,
                        execution_id=execution_id,
                    )

                app_obj = session.query(App).filter(App.id == app_id).first()
                if app_obj:
                    app_obj.state = AppState.RUNNING
                    app_obj.pid = process.pid
                else:
                    logger.error(
                        f"App record {app_id} ({app_name}) not found after process start",
                        app_id=app_id,
                    )

            # Reflect committed state on the detached object so callers see accurate values
            execution.status = ExecutionStatus.RUNNING
            execution.started_at = started_at
            execution.pid = process.pid
            execution.stdout_path = str(stdout_path)
            execution.stderr_path = str(stderr_path)

            self._processes[app_id] = process

            logger.info(
                f"App {app_name} started with PID {process.pid}",
                app_id=app_id,
                execution_id=execution_id,
            )

            return execution

        except Exception as e:
            logger.error(f"Failed to start app {app_name}: {e}", app_id=app_id)

            # Update execution and app state; execution_id may be None if the DB
            # insert itself failed (that's why the insert is inside this try block).
            with get_db() as session:
                if execution_id is not None:
                    exec_obj = session.query(Execution).filter(Execution.id == execution_id).first()
                    if exec_obj:
                        exec_obj.status = ExecutionStatus.FAILED
                        exec_obj.ended_at = datetime.now()
                        exec_obj.error_message = str(e)
                    else:
                        logger.warning(
                            f"Could not find execution record {execution_id} for app {app_name} during failure cleanup; record may remain in PENDING state",
                            app_id=app_id,
                            execution_id=execution_id,
                        )

                app_obj = session.query(App).filter(App.id == app_id).first()
                if app_obj:
                    app_obj.state = AppState.FAILED
                    app_obj.last_error = str(e)
                    app_obj.last_error_at = datetime.now()
                else:
                    logger.warning(
                        f"Could not find app record {app_id} ({app_name}) during failure cleanup",
                        app_id=app_id,
                    )

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

            # Close ALL running executions for this app — not just the first.
            # Orphaned RUNNING records accumulate if a previous _mark_stopped only
            # closed the oldest one while a new execution had already been created.
            executions = (
                session.query(Execution)
                .filter(
                    Execution.app_id == app.id,
                    Execution.status == ExecutionStatus.RUNNING,
                )
                .all()
            )
            now = datetime.now()
            for execution in executions:
                execution.status = ExecutionStatus.SUCCESS
                execution.ended_at = now

        # Remove from tracked processes
        if app.id in self._processes:
            del self._processes[app.id]

    def restart_app(self, app_id: int) -> Execution:
        """Restart an app.

        Accepts app_id rather than an App ORM object to avoid DetachedInstanceError
        when the caller's session has already committed and expired the object.
        """
        logger.info(f"Restarting app (id={app_id})", app_id=app_id)

        # Load a fresh App inside our own session so attribute access is always safe.
        # stop_app is called while the session is still open so its attribute reads work too.
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if app is None:
                raise RuntimeError(f"App {app_id} not found")
            if app.state == AppState.RUNNING:
                self.stop_app(app)

        # Wait a moment before restarting
        time.sleep(1)

        # Increment restart count
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app_id).first()
            if app_obj:
                app_obj.restart_count += 1
                app_obj.last_restart_at = datetime.now()

        return self.start_app(app_id)

    def adopt_app(self, app: App) -> None:
        """Re-adopt an orphaned perpetual app process, or start fresh if the process is gone.

        Called on startup for apps that were RUNNING or ENABLED before shutdown.
        If the process is still alive (e.g. survived a Mantyx-only restart), we
        re-register it so the supervisor can monitor and clean it up properly.
        If the process is gone (e.g. full system reboot), we reset state and start fresh.
        """
        if app.pid:
            try:
                process = psutil.Process(app.pid)
                if process.is_running() and process.status() != psutil.STATUS_ZOMBIE:
                    self._processes[app.id] = process
                    logger.info(
                        f"Adopted orphaned process for app: {app.name} (PID {app.pid})",
                        app_id=app.id,
                    )
                    return
            except psutil.NoSuchProcess:
                pass

        # Process is gone — reset state so start_app won't reject it, then launch fresh
        logger.info(
            f"No live process found for app: {app.name}, starting fresh",
            app_id=app.id,
        )
        exit_code = self._reap_process(app.pid)
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app.id).first()
            if app_obj:
                app_obj.state = AppState.ENABLED
                app_obj.pid = None
            self._close_orphaned_executions(app.id, session, exit_code=exit_code)

        self.start_app(app.id)

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
        # Collect IDs of apps that need restarting separately so the outer session
        # can be fully committed and closed before restart_app() opens its own sessions.
        # This prevents the two sessions from racing to update the same App row.
        to_restart: list[int] = []

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

                    exit_code = self._reap_process(app.pid)

                    if self._should_restart(app):
                        logger.info(f"Auto-restarting app {app.name}", app_id=app.id)
                        to_restart.append(app.id)
                    else:
                        # Mark as failed and close any orphaned running executions
                        logger.error(
                            f"App {app.name} exceeded max restarts",
                            app_id=app.id,
                        )
                        app.state = AppState.FAILED
                        app.last_error = "Exceeded maximum restart attempts"
                        app.last_error_at = datetime.now()
                        session.add(app)
                        self._close_orphaned_executions(app.id, session, exit_code=exit_code)
        # Outer session is now committed and closed. restart_app() opens its own
        # sessions with no risk of racing against the reads above.

        for app_id in to_restart:
            try:
                self.restart_app(app_id)
            except Exception as e:
                logger.error(
                    f"Failed to auto-restart app {app_id}: {e}",
                    app_id=app_id,
                )
                # Mark as failed in a fresh session — outer session is already closed
                with get_db() as session:
                    app_obj = session.query(App).filter(App.id == app_id).first()
                    if app_obj:
                        app_obj.state = AppState.FAILED
                        app_obj.last_error = str(e)
                        app_obj.last_error_at = datetime.now()
                    self._close_orphaned_executions(app_id, session, exit_code=None)

    def _close_orphaned_executions(
        self, app_id: int, session, exit_code: int | None = None
    ) -> None:
        """Close any RUNNING execution records that no longer have a live process."""
        executions = (
            session.query(Execution)
            .filter(
                Execution.app_id == app_id,
                Execution.status == ExecutionStatus.RUNNING,
            )
            .all()
        )
        now = datetime.now()
        for execution in executions:
            execution.status = ExecutionStatus.FAILED
            execution.ended_at = now
            if exit_code is not None:
                execution.exit_code = exit_code
                execution.error_message = (
                    f"Process (PID {execution.pid}) exited with code {exit_code}"
                )
            else:
                execution.error_message = (
                    f"Process (PID {execution.pid}) not found; closed by health monitor"
                )

    def _reap_process(self, pid: int | None) -> int | None:
        """Try to collect the exit code of a dead child process.

        Uses os.waitpid with WNOHANG so it never blocks. Returns the exit code
        if the process was reaped, or None if it was already reaped or not our child.
        """
        if pid is None:
            return None
        try:
            waited_pid, status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == 0:
                return None
            return os.waitstatus_to_exitcode(status)
        except ChildProcessError:
            # Process already reaped by someone else, or not our direct child
            return None
        except OSError:
            return None

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
                # _processes may hold subprocess.Popen or psutil.Process (adopted)
                if isinstance(process, psutil.Process):
                    is_alive = process.is_running() and process.status() != psutil.STATUS_ZOMBIE
                else:
                    is_alive = process.poll() is None

                if is_alive:
                    process.terminate()
                    try:
                        process.wait(timeout=5)
                    except (subprocess.TimeoutExpired, psutil.TimeoutExpired):
                        process.kill()
            except Exception as e:
                logger.error(f"Error cleaning up process for app {app_id}: {e}")
