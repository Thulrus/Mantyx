"""
Virtual environment management for apps.

Handles creation, dependency installation, and cleanup of isolated Python environments.
"""

import shutil
import subprocess
import sys
from pathlib import Path

from mantyx.config import get_settings
from mantyx.logging import get_logger

logger = get_logger("venv_manager")


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

    def create(self, app_name: str) -> None:
        """Create a new virtual environment for an app."""
        venv_path = self.get_venv_path(app_name)

        if venv_path.exists():
            logger.warning(f"Virtual environment already exists for {app_name}")
            return

        logger.info(f"Creating virtual environment for {app_name}")

        try:
            # Create venv using current Python
            subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                check=True,
                capture_output=True,
                text=True,
            )

            # Upgrade pip
            pip_path = self.get_pip_executable(app_name)
            subprocess.run(
                [str(pip_path), "install", "--upgrade", "pip"],
                check=True,
                capture_output=True,
                text=True,
            )

            logger.info(f"Virtual environment created successfully for {app_name}")
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Failed to create venv for {app_name}",
                details=f"stdout: {e.stdout}\nstderr: {e.stderr}",
            )
            # Clean up partial venv
            if venv_path.exists():
                shutil.rmtree(venv_path)
            raise RuntimeError(f"Failed to create virtual environment: {e.stderr}")

    def install_requirements(
        self,
        app_name: str,
        requirements_file: Path | None = None,
        requirements_list: list[str] | None = None,
    ) -> str:
        """
        Install requirements in an app's venv.

        Args:
            app_name: Name of the app
            requirements_file: Path to requirements.txt
            requirements_list: List of package specifications

        Returns:
            Installation output
        """
        if not self.exists(app_name):
            raise RuntimeError(f"No venv exists for {app_name}")

        pip_path = self.get_pip_executable(app_name)

        logger.info(f"Installing dependencies for {app_name}")

        try:
            if requirements_file and requirements_file.exists():
                result = subprocess.run(
                    [str(pip_path), "install", "-r", str(requirements_file)],
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,  # 5 minute timeout
                )
            elif requirements_list:
                result = subprocess.run(
                    [str(pip_path), "install"] + requirements_list,
                    check=True,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
            else:
                logger.info(f"No requirements to install for {app_name}")
                return "No requirements specified"

            logger.info(f"Dependencies installed successfully for {app_name}")
            return result.stdout

        except subprocess.TimeoutExpired:
            logger.error(f"Dependency installation timed out for {app_name}")
            raise RuntimeError("Dependency installation timed out")
        except subprocess.CalledProcessError as e:
            logger.error(
                f"Failed to install dependencies for {app_name}",
                details=f"stdout: {e.stdout}\nstderr: {e.stderr}",
            )
            raise RuntimeError(f"Failed to install dependencies: {e.stderr}")

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
