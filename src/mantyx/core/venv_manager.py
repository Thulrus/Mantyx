"""
Virtual environment management for apps.

Handles creation, dependency installation, and cleanup of isolated Python environments.
"""

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

from mantyx.config import get_settings
from mantyx.logging import get_logger

logger = get_logger("venv_manager")

LogCallback = Callable[[str], None]


def _run_streaming(cmd: list[str], on_log: LogCallback | None, timeout: int | None = None) -> str:
    """Run a subprocess, streaming stdout lines to on_log as they arrive.

    Returns the full combined output. Raises subprocess.CalledProcessError on
    non-zero exit (with .stdout/.stderr set to the collected output, mirroring
    subprocess.run's contract) and subprocess.TimeoutExpired on timeout.
    """
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    lines: list[str] = []
    try:
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.rstrip("\n")
            lines.append(line)
            if on_log and line:
                on_log(line)
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
        raise

    output = "\n".join(lines)
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

    def get_pip_executable(self, app_name: str) -> Path:
        """Get the path to pip in an app's venv."""
        venv_path = self.get_venv_path(app_name)
        return venv_path / "bin" / "pip"

    def exists(self, app_name: str) -> bool:
        """Check if a venv exists for an app."""
        python_path = self.get_python_executable(app_name)
        return python_path.exists()

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
            _run_streaming([sys.executable, "-m", "venv", str(venv_path)], on_log)

            # Upgrade pip
            if on_log:
                on_log("Upgrading pip...")
            pip_path = self.get_pip_executable(app_name)
            _run_streaming([str(pip_path), "install", "--upgrade", "pip"], on_log)

            logger.info(f"Virtual environment created successfully for {app_name}")
            if on_log:
                on_log("Virtual environment created.")
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Failed to create venv for {app_name}",
                details=f"output: {e.output}",
            )
            # Clean up partial venv
            if venv_path.exists():
                shutil.rmtree(venv_path)
            raise RuntimeError(f"Failed to create virtual environment: {e.output}")

    def install_requirements(
        self,
        app_name: str,
        requirements_file: Path | None = None,
        requirements_list: list[str] | None = None,
        on_log: LogCallback | None = None,
    ) -> str:
        """
        Install requirements in an app's venv.

        Args:
            app_name: Name of the app
            requirements_file: Path to requirements.txt
            requirements_list: List of package specifications
            on_log: Optional callback invoked with each line of pip output as
                it's produced, so callers can surface live progress.

        Returns:
            Installation output
        """
        if not self.exists(app_name):
            logger.info(f"No venv found for {app_name}, creating one")
            self.create(app_name, on_log=on_log)

        pip_path = self.get_pip_executable(app_name)

        logger.info(f"Installing dependencies for {app_name}")
        if on_log:
            on_log(f"Installing dependencies for {app_name}...")

        try:
            if requirements_file and requirements_file.exists():
                output = _run_streaming(
                    [str(pip_path), "install", "-r", str(requirements_file)],
                    on_log,
                    timeout=300,  # 5 minute timeout
                )
            elif requirements_list:
                output = _run_streaming(
                    [str(pip_path), "install"] + requirements_list,
                    on_log,
                    timeout=300,
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
            raise RuntimeError("Dependency installation timed out")
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

        pip_path = self.get_pip_executable(app_name)

        try:
            result = subprocess.run(
                [str(pip_path), "list", "--format=freeze"],
                check=True,
                capture_output=True,
                text=True,
            )
            return result.stdout.strip().split("\n")
        except subprocess.CalledProcessError:
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
