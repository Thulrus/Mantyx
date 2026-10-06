"""
Process supervisor for perpetual (long-running) applications.

Manages starting, stopping, and monitoring of app processes.
"""

import os
import signal
import subprocess
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import psutil

from mantyx.config import get_settings
from mantyx.core.port_detector import detect_listening_port
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_app_log_path, get_logger
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus

logger = get_logger("supervisor")

# States from which a perpetual app may be (re)started. UPLOADED apps have no
# environment yet, and DELETED apps are gone.
STARTABLE_STATES = (
    AppState.INSTALLED,
    AppState.ENABLED,
    AppState.DISABLED,
    AppState.STOPPED,
    AppState.FAILED,
    AppState.RUNNING,  # only when the recorded process is actually dead
)

SHUTDOWN_MESSAGE = "Stopped because Mantyx shut down; restarts automatically when Mantyx starts"


def build_app_env(app_name: str, app_environment: dict | None) -> dict[str, str]:
    """Environment for an app process: Mantyx's env, then defaults, then the app's own vars."""
    settings = get_settings()
    env = os.environ.copy()
    # Without this, print() output from an app redirected to a file is
    # block-buffered and shows up in the log viewer minutes late (or never,
    # if the process is killed). Apps can still override it.
    env.setdefault("PYTHONUNBUFFERED", "1")
    if app_environment:
        env.update({str(k): str(v) for k, v in app_environment.items()})

    # Inject persistent data directory so apps can store runtime data
    # that survives upgrades. Apps read: Path(os.environ["APP_DATA_DIR"])
    app_data_dir = settings.apps_dir / app_name / "data"
    app_data_dir.mkdir(parents=True, exist_ok=True)
    env["APP_DATA_DIR"] = str(app_data_dir)
    return env


def is_app_process(pid: int | None, app_name: str) -> bool:
    """True if `pid` is alive and really is this app's process.

    A bare "is the PID alive" check isn't enough: after a reboot the saved PID
    is often reused by an unrelated process, which we must never adopt or kill.
    Our processes are launched as `<venv>/bin/python <apps>/<name>/app/<entry>`,
    so the command line identifies them.
    """
    if not pid:
        return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running() or proc.status() == psutil.STATUS_ZOMBIE:
            return False
        cmdline = proc.cmdline()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return False

    settings = get_settings()
    markers: set[str] = set()
    for path in (settings.venvs_dir / app_name, settings.apps_dir / app_name):
        markers.add(str(path))
        try:
            markers.add(str(path.resolve()))
        except OSError:
            pass
    return any(marker in arg for arg in cmdline for marker in markers)


def terminate_process_tree(pid: int, timeout: float = 10) -> None:
    """SIGTERM the app's whole process group, escalating to SIGKILL after `timeout`.

    Apps are started with start_new_session=True, so they lead their own
    process group; signalling the group also stops any workers they spawned
    instead of leaving them orphaned.
    """
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, OSError):
        return
    use_group = pgid == pid

    def _send(sig: int) -> None:
        try:
            if use_group:
                os.killpg(pgid, sig)
            else:
                os.kill(pid, sig)
        except (ProcessLookupError, PermissionError, OSError):
            pass

    _send(signal.SIGTERM)

    try:
        psutil.Process(pid).wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        _send(signal.SIGKILL)
        try:
            psutil.Process(pid).wait(timeout=5)
        except (psutil.NoSuchProcess, psutil.TimeoutExpired):
            pass

    if use_group:
        # Give the rest of the group a moment to follow the leader, then make sure.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, OSError):
                return
            time.sleep(0.1)
        _send(signal.SIGKILL)


class ProcessSupervisor:
    """Supervises perpetual app processes."""

    def __init__(self):
        self.settings = get_settings()
        self.venv_manager = VenvManager()
        self._processes: dict[int, subprocess.Popen | psutil.Process] = {}
        self._locks: dict[int, threading.RLock] = {}
        self._locks_guard = threading.Lock()
        self._shutting_down = False

    def _app_lock(self, app_id: int) -> threading.RLock:
        """Serializes start/stop/restart per app so double-clicks can't race."""
        with self._locks_guard:
            lock = self._locks.get(app_id)
            if lock is None:
                lock = self._locks[app_id] = threading.RLock()
            return lock

    def _get_app_dir(self, app_name: str) -> Path:
        """Get the app's directory."""
        return self.settings.apps_dir / app_name / "app"

    def start_app(self, app_id: int, trigger_type: str = "manual") -> Execution:
        """Start a perpetual app.

        trigger_type is recorded on the execution: "manual", "startup"
        (Mantyx booted), "auto-restart" (crash recovery) or "update".
        """
        with self._app_lock(app_id):
            return self._start_app_locked(app_id, trigger_type)

    def _start_app_locked(self, app_id: int, trigger_type: str) -> Execution:
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
            current_pid = fresh.pid
            app_name = fresh.name
            app_entrypoint = fresh.entrypoint
            app_environment = fresh.environment

        if current_state == AppState.UPLOADED:
            raise RuntimeError(f"App {app_name} hasn't been installed yet")
        if current_state == AppState.DELETED:
            raise RuntimeError(f"App {app_name} has been deleted")
        if current_state == AppState.RUNNING:
            if is_app_process(current_pid, app_name):
                raise RuntimeError(f"App {app_name} is already running")
            # Recorded as running but the process is gone: close the stale run.
            with get_db() as session:
                self._close_orphaned_executions(app_id, session, exit_code=None)

        logger.debug(f"Starting app: {app_name}", app_id=app_id)

        # Create execution record inside the try block so any DB error is caught,
        # logged, and the app state is rolled back rather than silently 500-ing.
        execution_id: int | None = None
        try:
            execution = Execution(
                app_id=app_id,
                status=ExecutionStatus.PENDING,
                trigger_type=trigger_type,
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
                raise RuntimeError(
                    f"Virtual environment not found for {app_name}; use Rebuild environment"
                )

            # Prepare log files
            stdout_path, stderr_path = get_app_log_path(app_name, execution_id)

            env = build_app_env(app_name, app_environment)

            # Start process. Logs are opened in append mode so log rotation can
            # truncate them safely while the app keeps writing.
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
                    if trigger_type == "manual":
                        # A deliberate start gets a fresh crash budget.
                        app_obj.restart_count = 0
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

            reason = {
                "startup": " (Mantyx started)",
                "auto-restart": " after a crash",
                "update": " after an update",
            }.get(trigger_type, "")
            logger.info(
                f"{app_name} started{reason} (PID {process.pid})",
                app_id=app_id,
                execution_id=execution_id,
            )

            # Best-effort immediate attempt; servers usually haven't bound their
            # socket yet at this instant, so monitor_apps() keeps retrying below.
            self._maybe_detect_web_port(app_id, process.pid)

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
                    app_obj.pid = None
                    app_obj.last_error = f"Failed to start: {e}"
                    app_obj.last_error_at = datetime.now()
                else:
                    logger.warning(
                        f"Could not find app record {app_id} ({app_name}) during failure cleanup",
                        app_id=app_id,
                    )

            raise

    def stop_app(self, app: App, timeout: int = 10) -> None:
        """Stop a running app (and any processes it spawned)."""
        app_id, app_name, app_pid, app_state = app.id, app.name, app.pid, app.state
        with self._app_lock(app_id):
            if app_state != AppState.RUNNING or not app_pid:
                logger.warning(f"App {app_name} is not running", app_id=app_id)
                return

            logger.debug(f"Stopping app: {app_name} (PID: {app_pid})", app_id=app_id)

            try:
                if is_app_process(app_pid, app_name):
                    terminate_process_tree(app_pid, timeout=timeout)
                    logger.info(f"{app_name} stopped", app_id=app_id)
                else:
                    logger.debug(
                        f"Process {app_pid} for {app_name} was already gone", app_id=app_id
                    )
                self._reap_process(app_pid)
                self._mark_stopped(app_id)
            except Exception as e:
                logger.error(f"Error stopping app {app_name}: {e}", app_id=app_id)
                raise

    def _mark_stopped(self, app_id: int) -> None:
        """Mark an app as stopped in the database."""
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app_id).first()
            if app_obj:
                app_obj.state = AppState.STOPPED
                app_obj.pid = None
                # Clear auto-detected ports so a restart re-detects (some apps bind
                # a different port each run); never touch a user-set manual value.
                if app_obj.web_port_source == "auto":
                    app_obj.web_port = None
                    app_obj.web_port_source = None

            # Close ALL running executions for this app — not just the first.
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
                execution.status = ExecutionStatus.SUCCESS
                execution.ended_at = now

        self._processes.pop(app_id, None)

    def restart_app(self, app_id: int, trigger_type: str = "manual") -> Execution:
        """Restart an app.

        Accepts app_id rather than an App ORM object to avoid DetachedInstanceError
        when the caller's session has already committed and expired the object.
        Automatic restarts (trigger_type="auto-restart") count against the
        app's crash budget; manual ones reset it.
        """
        logger.debug(f"Restarting app (id={app_id})", app_id=app_id)

        with self._app_lock(app_id):
            # Load a fresh App inside our own session so attribute access is always safe.
            # stop_app is called while the session is still open so its attribute reads work too.
            with get_db() as session:
                app = session.query(App).filter(App.id == app_id).first()
                if app is None:
                    raise RuntimeError(f"App {app_id} not found")
                # After a crash the process is already gone; start_app() closes
                # the stale run itself, so there's nothing to stop.
                if app.state == AppState.RUNNING and (
                    trigger_type != "auto-restart" or self.check_app_running(app)
                ):
                    self.stop_app(app)

            # Wait a moment before restarting
            time.sleep(0.5)

            if trigger_type == "auto-restart":
                with get_db() as session:
                    app_obj = session.query(App).filter(App.id == app_id).first()
                    if app_obj:
                        app_obj.restart_count = (app_obj.restart_count or 0) + 1
                        app_obj.last_restart_at = datetime.now()

            return self.start_app(app_id, trigger_type=trigger_type)

    def reconcile_on_startup(self) -> None:
        """Close run records that can't still be running after a Mantyx restart.

        Scheduled runs are children of the Mantyx process, so any still marked
        running were interrupted. Perpetual runs are handled by adopt_app().
        """
        with get_db() as session:
            stale = (
                session.query(Execution)
                .join(App, App.id == Execution.app_id)
                .filter(
                    Execution.status.in_([ExecutionStatus.RUNNING, ExecutionStatus.PENDING]),
                    App.app_type == AppType.SCHEDULED,
                )
                .all()
            )
            now = datetime.now()
            for execution in stale:
                execution.status = ExecutionStatus.CANCELLED
                execution.ended_at = execution.ended_at or now
                execution.error_message = "Interrupted because Mantyx restarted during this run"

            # Perpetual apps that aren't supposed to be running can't own a live run.
            orphaned = (
                session.query(Execution)
                .join(App, App.id == Execution.app_id)
                .filter(
                    Execution.status.in_([ExecutionStatus.RUNNING, ExecutionStatus.PENDING]),
                    App.app_type == AppType.PERPETUAL,
                    App.state != AppState.RUNNING,
                )
                .all()
            )
            for execution in orphaned:
                execution.status = ExecutionStatus.CANCELLED
                execution.ended_at = execution.ended_at or now
                execution.error_message = execution.error_message or SHUTDOWN_MESSAGE

    def adopt_running_apps(self) -> None:
        """Adopt or start every perpetual app that should be running.

        Finds all non-deleted perpetual apps left in RUNNING, ENABLED, or
        FAILED state (e.g. from before a restart) and adopts each one via
        adopt_app(). Used both at server startup and after a backup restore.
        """
        with get_db() as session:
            perpetual_apps = (
                session.query(App)
                .filter(
                    App.app_type == AppType.PERPETUAL,
                    App.state.in_([AppState.RUNNING, AppState.ENABLED, AppState.FAILED]),
                    App.is_deleted == False,  # noqa: E712
                )
                .all()
            )
            # Detach from session before iterating (avoids DetachedInstanceError)
            session.expunge_all()

        for app in perpetual_apps:
            try:
                self.adopt_app(app)
            except Exception as e:
                logger.error(
                    f"{app.name} couldn't be started when Mantyx started: {e}",
                    app_id=app.id,
                )

    def adopt_app(self, app: App) -> None:
        """Re-adopt an orphaned perpetual app process, or start fresh if the process is gone.

        Called on startup for apps that were RUNNING or ENABLED before shutdown.
        If the process is still alive (e.g. survived a Mantyx-only restart), we
        re-register it so the supervisor can monitor and clean it up properly.
        If the process is gone (e.g. full system reboot), we reset state and start fresh.
        """
        if app.pid and is_app_process(app.pid, app.name):
            try:
                self._processes[app.id] = psutil.Process(app.pid)
            except psutil.NoSuchProcess:
                pass
            else:
                logger.info(
                    f"Adopted running process for app: {app.name} (PID {app.pid})",
                    app_id=app.id,
                )
                return

        # Process is gone — reset state so start_app won't reject it, then launch fresh
        logger.debug(f"Starting {app.name} (Mantyx started)", app_id=app.id)
        self._reap_process(app.pid)
        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app.id).first()
            if app_obj:
                app_obj.state = AppState.ENABLED
                app_obj.pid = None
            # Almost always the process ended because Mantyx (or the machine)
            # restarted, e.g. during a deploy; don't record that as a crash.
            now = datetime.now()
            for execution in (
                session.query(Execution)
                .filter(
                    Execution.app_id == app.id,
                    Execution.status.in_([ExecutionStatus.RUNNING, ExecutionStatus.PENDING]),
                )
                .all()
            ):
                execution.status = ExecutionStatus.CANCELLED
                execution.ended_at = now
                execution.error_message = "Ended when Mantyx restarted"

        self.start_app(app.id, trigger_type="startup")

    def _maybe_detect_web_port(self, app_id: int, pid: int | None) -> None:
        """Try to auto-populate an app's web_port from its process's open sockets.

        No-ops once a port has been found or the user has manually set/edited
        web_url/web_port (App.web_port_source == "manual") — see api/apps.py's
        update_app_config, which flips that flag on any manual edit.
        """
        if pid is None:
            return

        port = detect_listening_port(pid)
        if port is None:
            return

        with get_db() as session:
            app_obj = session.query(App).filter(App.id == app_id).first()
            if app_obj is None or app_obj.web_port_source == "manual" or app_obj.web_port:
                return
            app_obj.web_port = port
            app_obj.web_port_source = "auto"
            logger.info(f"Auto-detected web port {port} for app {app_obj.name}", app_id=app_id)

    def check_app_running(self, app: App) -> bool:
        """Check if an app's recorded process is alive and really is that app."""
        return is_app_process(app.pid, app.name)

    def monitor_apps(self) -> None:
        """Monitor all running apps and handle failures."""
        from mantyx.core import runtime

        if self._shutting_down or runtime.is_shutting_down():
            return

        # Collect IDs of apps that need restarting separately so the outer session
        # can be fully committed and closed before restart_app() opens its own sessions.
        # This prevents the two sessions from racing to update the same App row.
        to_restart: list[int] = []

        with get_db() as session:
            running_apps = (
                session.query(App)
                .filter(
                    App.state == AppState.RUNNING,
                    App.is_deleted == False,  # noqa: E712
                )
                .all()
            )

            for app in running_apps:
                lock = self._app_lock(app.id)
                if not lock.acquire(blocking=False):
                    # A start/stop/update is in progress for this app; check next tick.
                    continue
                try:
                    if self.check_app_running(app):
                        if app.web_port_source != "manual" and not app.web_port:
                            self._maybe_detect_web_port(app.id, app.pid)
                        continue

                    exit_code = self._reap_process(app.pid)
                    exit_desc = (
                        f"exit code {exit_code}" if exit_code is not None else "unknown exit code"
                    )
                    logger.warning(f"{app.name} stopped unexpectedly ({exit_desc})", app_id=app.id)

                    app.last_error = f"Process exited unexpectedly ({exit_desc})"
                    app.last_error_at = datetime.now()
                    self._close_orphaned_executions(app.id, session, exit_code=exit_code)

                    if app.restart_policy == "never":
                        app.state = AppState.FAILED
                        app.pid = None
                        app.last_error = (
                            f"Process exited ({exit_desc}); automatic restart is turned off"
                        )
                    elif self._should_restart(app):
                        delay = app.restart_delay or 0
                        if app.last_restart_at and delay:
                            since = (datetime.now() - _naive(app.last_restart_at)).total_seconds()
                            if since < delay:
                                # Restarted very recently; wait out the delay next tick.
                                continue
                        logger.debug(f"Auto-restarting app {app.name}", app_id=app.id)
                        to_restart.append(app.id)
                    else:
                        logger.error(
                            f"{app.name} kept crashing, so Mantyx stopped restarting it",
                            app_id=app.id,
                        )
                        app.state = AppState.FAILED
                        app.pid = None
                        app.last_error = (
                            f"Exceeded maximum restart attempts: crashed {app.restart_count + 1} "
                            f"times within {self.settings.restart_window // 60} minutes "
                            f"(last {exit_desc})"
                        )
                    session.add(app)
                finally:
                    lock.release()
        # Outer session is now committed and closed. restart_app() opens its own
        # sessions with no risk of racing against the reads above.

        for app_id in to_restart:
            try:
                self.restart_app(app_id, trigger_type="auto-restart")
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
                Execution.status.in_([ExecutionStatus.RUNNING, ExecutionStatus.PENDING]),
            )
            .all()
        )
        now = datetime.now()
        for execution in executions:
            execution.status = ExecutionStatus.FAILED
            execution.ended_at = now
            if exit_code is not None:
                execution.exit_code = exit_code
                execution.error_message = f"Process exited unexpectedly with code {exit_code}"
            else:
                execution.error_message = "Process stopped unexpectedly"

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
                if datetime.now() - _naive(app.last_restart_at) > window:
                    # Reset count if outside window
                    app.restart_count = 0

            return (app.restart_count or 0) < app.max_restarts

        return False

    def shutdown(self, timeout: float = 8) -> None:
        """Stop all perpetual app processes because Mantyx itself is stopping.

        App states are deliberately left as RUNNING (with the PID cleared) so
        every app that was running comes back automatically when Mantyx starts
        again — e.g. right after a deploy restarts the service.
        """
        self._shutting_down = True
        logger.info("Stopping app processes for shutdown")

        with get_db() as session:
            running = (
                session.query(App)
                .filter(App.state == AppState.RUNNING, App.is_deleted == False)  # noqa: E712
                .all()
            )
            targets = [(a.id, a.name, a.pid) for a in running]

        ours = [(aid, name, pid) for aid, name, pid in targets if is_app_process(pid, name)]

        # Signal everything first, then wait once, so shutdown time doesn't
        # grow with the number of apps.
        threads = [
            threading.Thread(target=terminate_process_tree, args=(pid, timeout), daemon=True)
            for _, _, pid in ours
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout + 8)

        with get_db() as session:
            now = datetime.now()
            for app_id, _, pid in targets:
                self._reap_process(pid)
                app_obj = session.query(App).filter(App.id == app_id).first()
                if app_obj:
                    app_obj.pid = None
                for execution in (
                    session.query(Execution)
                    .filter(
                        Execution.app_id == app_id,
                        Execution.status == ExecutionStatus.RUNNING,
                    )
                    .all()
                ):
                    execution.status = ExecutionStatus.CANCELLED
                    execution.ended_at = now
                    execution.error_message = SHUTDOWN_MESSAGE
        self._processes.clear()

    def cleanup(self) -> None:
        """Backward-compatible alias for shutdown()."""
        self.shutdown()


def _naive(dt: datetime) -> datetime:
    """SQLite hands back naive datetimes; normalise any aware ones to compare safely."""
    if dt.tzinfo is not None:
        return dt.astimezone().replace(tzinfo=None)
    return dt
