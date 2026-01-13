"""
Application manager handling full app lifecycle.

Coordinates uploads, installations, updates, and deletions.
"""

import json
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

import yaml
from git import Repo

from mantyx.config import get_settings
from mantyx.core.scheduler import AppScheduler
from mantyx.core.supervisor import ProcessSupervisor
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState, AppType
from mantyx.models.schedule import Schedule

logger = get_logger("app_manager")


class AppManager:
    """Manages application lifecycle operations."""

    def __init__(
        self,
        venv_manager: Optional[VenvManager] = None,
        supervisor: Optional[ProcessSupervisor] = None,
        scheduler: Optional[AppScheduler] = None,
    ):
        self.settings = get_settings()
        self.venv_manager = venv_manager or VenvManager()
        self.supervisor = supervisor or ProcessSupervisor()
        self.scheduler = scheduler or AppScheduler()

    def _get_app_dir(self, app_name: str) -> Path:
        """Get the app's base directory."""
        return self.settings.apps_dir / app_name

    def _get_app_source_dir(self, app_name: str) -> Path:
        """Get the app's source code directory."""
        return self._get_app_dir(app_name) / "app"

    def _validate_upload(self, file_path: Path) -> None:
        """Validate an uploaded file."""
        if not file_path.exists():
            raise ValueError("Upload file not found")

        size_mb = file_path.stat().st_size / (1024 * 1024)
        if size_mb > self.settings.max_upload_size_mb:
            raise ValueError(f"Upload size ({size_mb:.1f}MB) exceeds limit "
                             f"({self.settings.max_upload_size_mb}MB)")

    def create_app_from_zip(
        self,
        zip_path: Path,
        app_name: str,
        display_name: str,
        description: Optional[str] = None,
        app_type: AppType = AppType.PERPETUAL,
    ) -> dict[str, int | str]:
        """Create an app from a ZIP archive."""
        logger.info(f"Creating app {app_name} from ZIP: {zip_path}")

        self._validate_upload(zip_path)

        # Check if app already exists
        with get_db() as session:
            existing = session.query(App).filter(App.name == app_name).first()
            if existing:
                if not existing.is_deleted:
                    raise ValueError(f"App {app_name} already exists")
                # Delete the old entry to avoid UNIQUE constraint issues
                session.delete(existing)
                session.commit()

        app_dir = self._get_app_dir(app_name)
        source_dir = self._get_app_source_dir(app_name)

        try:
            # Extract ZIP
            source_dir.mkdir(parents=True, exist_ok=True)

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # Security: check for path traversal
                for member in zip_ref.namelist():
                    if member.startswith('/') or '..' in member:
                        raise ValueError(f"Invalid path in ZIP: {member}")

                zip_ref.extractall(source_dir)

            logger.info(f"Extracted ZIP to {source_dir}")

            # Detect entrypoint
            entrypoint = self._detect_entrypoint(source_dir)

            # Create app record
            app = App(
                name=app_name,
                display_name=display_name,
                description=description,
                app_type=app_type,
                state=AppState.UPLOADED,
                entrypoint=entrypoint,
                version="1.0.0",
            )

            with get_db() as session:
                session.add(app)
                session.commit()
                session.refresh(app)  # Reload to get all attributes
                # Extract values while session is active
                app_id = app.id
                app_name = app.name

            logger.info(f"Created app {app_name} with ID {app_id}",
                        app_id=app_id)

            # Return the values as a simple dict to avoid session issues
            return {"id": app_id, "name": app_name}

        except Exception as e:
            # Clean up on failure
            if app_dir.exists():
                shutil.rmtree(app_dir)
            logger.error(f"Failed to create app from ZIP: {e}")
            raise

    def create_app_from_git(
        self,
        git_url: str,
        app_name: str,
        display_name: str,
        branch: str = "main",
        description: Optional[str] = None,
        app_type: AppType = AppType.PERPETUAL,
    ) -> dict[str, int | str]:
        """Create an app from a Git repository."""
        logger.info(f"Creating app {app_name} from Git: {git_url}")

        # Check if app already exists
        with get_db() as session:
            existing = session.query(App).filter(App.name == app_name).first()
            if existing:
                if not existing.is_deleted:
                    raise ValueError(f"App {app_name} already exists")
                # Delete the old entry to avoid UNIQUE constraint issues
                session.delete(existing)
                session.commit()

        source_dir = self._get_app_source_dir(app_name)

        try:
            # Clone repository
            source_dir.mkdir(parents=True, exist_ok=True)
            repo = Repo.clone_from(git_url, source_dir, branch=branch)

            commit_hash = repo.head.commit.hexsha
            logger.info(f"Cloned {git_url} @ {commit_hash}")

            # Detect entrypoint
            entrypoint = self._detect_entrypoint(source_dir)

            # Create app record
            app = App(
                name=app_name,
                display_name=display_name,
                description=description,
                app_type=app_type,
                state=AppState.UPLOADED,
                entrypoint=entrypoint,
                version="1.0.0",
                git_url=git_url,
                git_branch=branch,
                git_commit=commit_hash,
            )

            with get_db() as session:
                session.add(app)
                session.commit()
                session.refresh(app)  # Ensure all attributes are loaded
                # Extract values while session is active
                app_id = app.id
                app_name = app.name

            logger.info(f"Created app {app_name} from Git", app_id=app_id)

            # Return the values as a simple dict to avoid session issues
            return {"id": app_id, "name": app_name}

        except Exception as e:
            # Clean up on failure
            if self._get_app_dir(app_name).exists():
                shutil.rmtree(self._get_app_dir(app_name))
            logger.error(f"Failed to create app from Git: {e}")
            raise

    def _detect_entrypoint(self, source_dir: Path) -> str:
        """Detect the entrypoint file for an app."""
        # Look for common entrypoint files
        candidates = ["main.py", "app.py", "__main__.py", "run.py", "start.py"]

        for candidate in candidates:
            if (source_dir / candidate).exists():
                return candidate

        # Look for any Python file
        py_files = list(source_dir.glob("*.py"))
        if py_files:
            return py_files[0].name

        raise ValueError("No Python entrypoint found in app")

    def install_app(self, app_id: int) -> None:
        """Install an app's dependencies."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if app.state != AppState.UPLOADED:
                raise ValueError(f"App {app.name} is not in uploaded state")

            logger.info(f"Installing app {app.name}", app_id=app.id)

            # Create virtual environment
            self.venv_manager.create(app.name)

            # Check for requirements
            source_dir = self._get_app_source_dir(app.name)
            requirements_file = source_dir / "requirements.txt"

            if requirements_file.exists():
                logger.info(f"Installing requirements for {app.name}",
                            app_id=app.id)
                self.venv_manager.install_requirements(app.name,
                                                       requirements_file)
            else:
                logger.info(f"No requirements.txt found for {app.name}",
                            app_id=app.id)

            # Update state
            app.state = AppState.INSTALLED
            session.add(app)

            logger.info(f"App {app.name} installed successfully",
                        app_id=app.id)

    def enable_app(self, app_id: int) -> None:
        """Enable an app."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.can_enable:
                raise ValueError(
                    f"App {app.name} cannot be enabled from state {app.state}")

            logger.info(f"Enabling app {app.name}", app_id=app.id)

            app.state = AppState.ENABLED
            session.add(app)

            # If perpetual app, start it
            if app.app_type == AppType.PERPETUAL:
                self.supervisor.start_app(app)

            logger.info(f"App {app.name} enabled", app_id=app.id)

    def disable_app(self, app_id: int) -> None:
        """Disable an app."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.can_disable:
                raise ValueError(
                    f"App {app.name} cannot be disabled from state {app.state}"
                )

            logger.info(f"Disabling app {app.name}", app_id=app.id)

            # Stop if running
            if app.state == AppState.RUNNING:
                self.supervisor.stop_app(app)

            app.state = AppState.DISABLED
            session.add(app)

            logger.info(f"App {app.name} disabled", app_id=app.id)

    def update_app(self,
                   app_id: int,
                   new_source: Path,
                   backup: bool = True) -> None:
        """Update an app's source code."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            logger.info(f"Updating app {app.name}", app_id=app.id)

            was_running = app.state == AppState.RUNNING

            # Stop if running
            if was_running:
                self.supervisor.stop_app(app)

            # Backup if requested
            if backup:
                self._backup_app(app.name)

            # Replace source
            source_dir = self._get_app_source_dir(app.name)
            temp_dir = self.settings.temp_dir / f"{app.name}_update"

            try:
                # Extract new source to temp
                temp_dir.mkdir(parents=True, exist_ok=True)

                with zipfile.ZipFile(new_source, 'r') as zip_ref:
                    zip_ref.extractall(temp_dir)

                # Remove old source and move new
                shutil.rmtree(source_dir)
                shutil.move(str(temp_dir), str(source_dir))

                # Reinstall dependencies
                requirements_file = source_dir / "requirements.txt"
                if requirements_file.exists():
                    self.venv_manager.install_requirements(
                        app.name, requirements_file)

                # Increment version
                version_parts = app.version.split('.')
                version_parts[-1] = str(int(version_parts[-1]) + 1)
                app.version = '.'.join(version_parts)
                session.add(app)

                # Restart if was running
                if was_running:
                    self.supervisor.start_app(app)

                logger.info(f"App {app.name} updated successfully",
                            app_id=app.id)

            except Exception as e:
                logger.error(f"Failed to update app {app.name}: {e}",
                             app_id=app.id)
                # TODO: Implement rollback from backup
                raise
            finally:
                if temp_dir.exists():
                    shutil.rmtree(temp_dir)

    def _backup_app(self, app_name: str) -> Path:
        """Create a backup of an app."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.settings.backups_dir / app_name / timestamp
        backup_dir.mkdir(parents=True, exist_ok=True)

        source_dir = self._get_app_source_dir(app_name)
        shutil.copytree(source_dir, backup_dir / "app")

        logger.info(f"Created backup for {app_name} at {backup_dir}")
        return backup_dir

    def delete_app(self, app_id: int, soft: bool = True) -> None:
        """Delete an app."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            logger.info(f"Deleting app {app.name} (soft={soft})",
                        app_id=app.id)

            # Stop if running
            if app.state == AppState.RUNNING:
                self.supervisor.stop_app(app)

            # Remove schedules
            for schedule in app.schedules:
                self.scheduler.remove_schedule(schedule.id)

            if soft:
                # Soft delete
                app.is_deleted = True
                app.deleted_at = datetime.now()
                app.state = AppState.DELETED
                session.add(app)
            else:
                # Hard delete
                app_dir = self._get_app_dir(app.name)
                if app_dir.exists():
                    shutil.rmtree(app_dir)

                self.venv_manager.remove(app.name)

                session.delete(app)

            logger.info(f"App {app.name} deleted", app_id=app.id)
