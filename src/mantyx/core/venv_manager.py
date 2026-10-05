"""
Virtual environment management for apps.

Handles creation, dependency installation, and cleanup of isolated Python environments.
"""

import shutil
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path

from mantyx.config import get_settings
from mantyx.logging import get_logger

logger = get_logger("venv_manager")

LogCallback = Callable[[str], None]

# How long `python -m pip --version` may take before the venv counts as unhealthy.
HEALTH_CHECK_TIMEOUT = 30


def _describe_os_error(e: OSError) -> str:
    """Human-readable OSError detail without the bare "[Errno N]" prefix."""
    detail = e.strerror or str(e)
    if e.filename:
        detail = f"{detail}: {e.filename}"
    return detail


def _run_streaming(cmd: list[str], on_log: LogCallback | None, timeout: int | None = None) -> str:
    """Run a subprocess, streaming stdout lines to on_log as they arrive.

    Returns the full combined output. Raises subprocess.CalledProcessError on
    non-zero exit (with .stdout/.stderr set to the collected output, mirroring
    subprocess.run's contract), subprocess.TimeoutExpired on timeout, and
    OSError if the command can't be launched at all.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    # Reading stdout blocks until the process closes it, so a wait(timeout=...)
    # after the loop would never fire for a hung-but-chatty (or silent) process.
    # A watchdog enforces the deadline while we're still streaming.
    timed_out = threading.Event()

    def _kill_on_timeout() -> None:
        timed_out.set()
        process.kill()

    watchdog = threading.Timer(timeout, _kill_on_timeout) if timeout else None
    if watchdog:
        watchdog.daemon = True
        watchdog.start()

    lines: list[str] = []
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            lines.append(line)
            if on_log and line:
                on_log(line)
        returncode = process.wait()
    finally:
        if watchdog:
            watchdog.cancel()
        if process.poll() is None:
            process.kill()
            process.wait()

    output = "\n".join(lines)
    if timed_out.is_set():
        raise subprocess.TimeoutExpired(cmd, timeout, output=output)
    if returncode != 0:
        raise subprocess.CalledProcessError(returncode, cmd, output=output, stderr=output)
    return output


class VenvManager:
    """Manages virtual environments for applications."""

    def __init__(self):
        self.settings = get_settings()

    def get_venv_path(self, app_name: str) -> Path:
        """Get the path to an app's virtual environment."""
        return self.settings.venvs_dir / app_name

    def get_python_executable(self, app_name: str) -> Path:
        """Get the path to the Python executable in an app's venv."""
        venv_path = self.get_venv_path(app_name)
        return venv_path / "bin" / "python"

    def _pip_command(self, app_name: str, *args: str) -> list[str]:
        """Build a pip invocation that runs via the venv's interpreter.

        Never call bin/pip directly: console scripts hardcode the venv's absolute
        path in their shebang, so they break if the venv directory is moved.
        """
        return [str(self.get_python_executable(app_name)), "-m", "pip", *args]

    def _run_in_venv(
        self,
        app_name: str,
        cmd: list[str],
        on_log: LogCallback | None,
        timeout: int | None = None,
    ) -> str:
        """Run a command with the venv's interpreter, turning launch failures into
        a readable RuntimeError instead of a bare "[Errno 2] ..."."""
        try:
            return _run_streaming(cmd, on_log, timeout=timeout)
        except OSError as e:
            message = (
                f"Could not run pip for app {app_name}'s environment "
                f"({_describe_os_error(e)}); the environment may need rebuilding"
            )
            logger.error(message)
            raise RuntimeError(message) from e

    def exists(self, app_name: str) -> bool:
        """Check if a venv exists for an app."""
        python_path = self.get_python_executable(app_name)
        return python_path.exists()

    def is_healthy(self, app_name: str) -> bool:
        """Check that the venv's interpreter runs and can import pip.

        Catches venvs whose bin/python symlink target vanished (e.g. after an OS
        Python upgrade) or whose pip install is broken.
        """
        if not self.exists(app_name):
            return False
        try:
            subprocess.run(
                self._pip_command(app_name, "--version"),
                check=True,
                capture_output=True,
                timeout=HEALTH_CHECK_TIMEOUT,
            )
            return True
        except (OSError, subprocess.SubprocessError):
            return False

    def ensure_healthy(self, app_name: str, on_log: LogCallback | None = None) -> None:
        """Make sure an app's venv exists and pip works, repairing it if needed.

        Missing venvs are created. Unhealthy ones are first repaired with
        `python -m ensurepip --upgrade`; if that doesn't help, the venv is deleted
        and recreated from scratch.
        """

        def log(message: str, level: str = "info") -> None:
            getattr(logger, level)(message)
            if on_log:
                on_log(message)

        if not self.get_venv_path(app_name).exists():
            log(f"No virtual environment found for {app_name}, creating one")
            self.create(app_name, on_log=on_log)
            return

        if self.is_healthy(app_name):
            return

        log(
            f"Virtual environment for {app_name} is unhealthy; attempting repair with ensurepip",
            "warning",
        )
        if self.exists(app_name):
            try:
                self._run_in_venv(
                    app_name,
                    [str(self.get_python_executable(app_name)), "-m", "ensurepip", "--upgrade"],
                    on_log,
                    timeout=self.settings.pip_timeout_seconds,
                )
            except (RuntimeError, subprocess.SubprocessError) as e:
                logger.warning(f"ensurepip failed for {app_name}: {e}")

        if self.is_healthy(app_name):
            log(f"Repaired virtual environment for {app_name} with ensurepip")
            return

        log(
            f"Repair failed; rebuilding virtual environment for {app_name} from scratch",
            "warning",
        )
        self.remove(app_name)
        self.create(app_name, on_log=on_log)
        log(f"Rebuilt virtual environment for {app_name}")

    def create(self, app_name: str, on_log: LogCallback | None = None) -> None:
        """Create a new virtual environment for an app."""
        venv_path = self.get_venv_path(app_name)

        if venv_path.exists():
            logger.warning(f"Virtual environment already exists for {app_name}")
            return

        logger.info(f"Creating virtual environment for {app_name}")
        if on_log:
            on_log(f"Creating virtual environment for {app_name}...")

        try:
            # Create venv using current Python
            try:
                _run_streaming([sys.executable, "-m", "venv", str(venv_path)], on_log)
            except OSError as e:
                raise RuntimeError(
                    f"Could not create virtual environment for app {app_name} "
                    f"({_describe_os_error(e)})"
                ) from e

            # Upgrade pip
            if on_log:
                on_log("Upgrading pip...")
            self._run_in_venv(
                app_name,
                self._pip_command(app_name, "install", "--upgrade", "pip"),
                on_log,
                timeout=self.settings.pip_timeout_seconds,
            )

            logger.info(f"Virtual environment created successfully for {app_name}")
            if on_log:
                on_log("Virtual environment created.")
        except (RuntimeError, subprocess.SubprocessError) as e:
            output = getattr(e, "output", None) or str(e)
            logger.error(
                f"Failed to create venv for {app_name}",
                details=f"output: {output}",
            )
            # Clean up partial venv
            if venv_path.exists():
                shutil.rmtree(venv_path)
            if isinstance(e, RuntimeError):
                raise
            raise RuntimeError(f"Failed to create virtual environment: {output}") from e

    def rebuild(
        self,
        app_name: str,
        requirements_file: Path | None = None,
        on_log: LogCallback | None = None,
    ) -> str:
        """Delete and recreate an app's venv, then reinstall its requirements."""
        logger.info(f"Rebuilding virtual environment for {app_name}")
        if on_log:
            on_log(f"Removing virtual environment for {app_name}...")
        self.remove(app_name)
        self.create(app_name, on_log=on_log)
        return self.install_requirements(app_name, requirements_file, on_log=on_log)

    def install_requirements(
        self,
        app_name: str,
        requirements_file: Path | None = None,
        requirements_list: list[str] | None = None,
        on_log: LogCallback | None = None,
    ) -> str:
        """
        Install requirements in an app's venv.

        The venv is health-checked first and repaired or recreated if needed.

        Args:
            app_name: Name of the app
            requirements_file: Path to requirements.txt
            requirements_list: List of package specifications
            on_log: Optional callback invoked with each line of pip output as
                it's produced, so callers can surface live progress.

        Returns:
            Installation output
        """
        self.ensure_healthy(app_name, on_log=on_log)

        logger.info(f"Installing dependencies for {app_name}")
        if on_log:
            on_log(f"Installing dependencies for {app_name}...")

        timeout = self.settings.pip_timeout_seconds
        try:
            if requirements_file and requirements_file.exists():
                output = self._run_in_venv(
                    app_name,
                    self._pip_command(app_name, "install", "-r", str(requirements_file)),
                    on_log,
                    timeout=timeout,
                )
            elif requirements_list:
                output = self._run_in_venv(
                    app_name,
                    self._pip_command(app_name, "install", *requirements_list),
                    on_log,
                    timeout=timeout,
                )
            else:
                logger.info(f"No requirements to install for {app_name}")
                if on_log:
                    on_log("No requirements to install.")
                return "No requirements specified"

            logger.info(f"Dependencies installed successfully for {app_name}")
            if on_log:
                on_log("Dependencies installed successfully.")
            return output

        except subprocess.TimeoutExpired:
            logger.error(f"Dependency installation timed out for {app_name}")
            raise RuntimeError(
                f"Dependency installation timed out after {timeout}s "
                "(raise MANTYX_PIP_TIMEOUT if this app has heavy dependencies)"
            )
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Failed to install dependencies for {app_name}",
                details=f"output: {e.output}",
            )
            raise RuntimeError(f"Failed to install dependencies: {e.output}")

    def list_packages(self, app_name: str) -> list[str]:
        """List installed packages in an app's venv."""
        if not self.exists(app_name):
            return []

        try:
            result = subprocess.run(
                self._pip_command(app_name, "list", "--format=freeze"),
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().split("\n")
        except (OSError, subprocess.CalledProcessError):
            logger.error(f"Failed to list packages for {app_name}")
            return []

    def remove(self, app_name: str) -> None:
        """Remove an app's virtual environment."""
        venv_path = self.get_venv_path(app_name)

        if not venv_path.exists():
            logger.warning(f"No venv to remove for {app_name}")
            return

        logger.info(f"Removing virtual environment for {app_name}")

        try:
            shutil.rmtree(venv_path)
            logger.info(f"Virtual environment removed for {app_name}")
        except Exception as e:
            logger.error(f"Failed to remove venv for {app_name}: {e}")
            raise RuntimeError(f"Failed to remove virtual environment: {e}")
