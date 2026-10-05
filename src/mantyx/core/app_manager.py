"""
Application manager handling full app lifecycle.

Coordinates uploads, installations, updates, and deletions.
"""

import shutil
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from git import RemoteProgress, Repo
from git import exc as git_exc

from mantyx.config import get_settings
from mantyx.core.scheduler import AppScheduler
from mantyx.core.supervisor import ProcessSupervisor
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState, AppType

LogCallback = Callable[[str], None]

logger = get_logger("app_manager")


class _GitLogProgress(RemoteProgress):
    """Forwards GitPython clone/pull progress lines to a log callback."""

    def __init__(self, on_log: LogCallback):
        super().__init__()
        self._on_log = on_log

    def update(self, op_code, cur_count, max_count=None, message=""):
        line = self._cur_line
        if line:
            self._on_log(line)


class AppManager:
    """Manages application lifecycle operations."""

    def __init__(
        self,
        venv_manager: VenvManager | None = None,
        supervisor: ProcessSupervisor | None = None,
        scheduler: AppScheduler | None = None,
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
            raise ValueError(
                f"Upload size ({size_mb:.1f}MB) exceeds limit "
                f"({self.settings.max_upload_size_mb}MB)"
            )

    def create_app_from_zip(
        self,
        zip_path: Path,
        app_name: str,
        display_name: str,
        description: str | None = None,
        app_type: AppType = AppType.PERPETUAL,
        on_log: LogCallback | None = None,
    ) -> dict[str, int | str]:
        """Create an app from a ZIP archive."""
        logger.info(f"Creating app {app_name} from ZIP: {zip_path}")
        if on_log:
            on_log(f"Validating upload for {app_name}...")

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

            if on_log:
                on_log(f"Extracting {zip_path.name}...")

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # Security: check for path traversal
                for member in zip_ref.namelist():
                    if member.startswith("/") or ".." in member:
                        raise ValueError(f"Invalid path in ZIP: {member}")

                zip_ref.extractall(source_dir)

            logger.info(f"Extracted ZIP to {source_dir}")
            if on_log:
                on_log("Extraction complete.")

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

            logger.info(f"Created app {app_name} with ID {app_id}", app_id=app_id)
            if on_log:
                on_log(f"App {app_name} created.")

            # Return the values as a simple dict to avoid session issues
            return {"id": app_id, "name": app_name}

        except Exception as e:
            # Clean up on failure
            if app_dir.exists():
                shutil.rmtree(app_dir)
            logger.error(f"Failed to create app from ZIP: {e}")
            if on_log:
                on_log(f"Failed: {e}")
            raise

    def create_app_from_git(
        self,
        git_url: str,
        app_name: str,
        display_name: str,
        branch: str = "main",
        description: str | None = None,
        app_type: AppType = AppType.PERPETUAL,
        on_log: LogCallback | None = None,
    ) -> dict[str, int | str]:
        """Create an app from a Git repository."""
        logger.info(f"Creating app {app_name} from Git: {git_url}")
        if on_log:
            on_log(f"Cloning {git_url} (branch {branch})...")

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
            progress = _GitLogProgress(on_log) if on_log else None
            repo = Repo.clone_from(git_url, source_dir, branch=branch, progress=progress)

            commit_hash = repo.head.commit.hexsha
            logger.info(f"Cloned {git_url} @ {commit_hash}")
            if on_log:
                on_log(f"Cloned at commit {commit_hash[:8]}.")

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
            if on_log:
                on_log(f"App {app_name} created.")

            # Return the values as a simple dict to avoid session issues
            return {"id": app_id, "name": app_name}

        except Exception as e:
            # Clean up on failure
            if self._get_app_dir(app_name).exists():
                shutil.rmtree(self._get_app_dir(app_name))
            logger.error(f"Failed to create app from Git: {e}")
            if on_log:
                on_log(f"Failed: {e}")
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

    def install_app(self, app_id: int, on_log: LogCallback | None = None) -> None:
        """Install an app's dependencies."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if app.state != AppState.UPLOADED:
                raise ValueError(f"App {app.name} is not in uploaded state")

            logger.info(f"Installing app {app.name}", app_id=app.id)

            # Create virtual environment
            self.venv_manager.create(app.name, on_log=on_log)

            # Check for requirements
            source_dir = self._get_app_source_dir(app.name)
            requirements_file = source_dir / "requirements.txt"

            if requirements_file.exists():
                logger.info(f"Installing requirements for {app.name}", app_id=app.id)
                self.venv_manager.install_requirements(app.name, requirements_file, on_log=on_log)
            else:
                logger.info(f"No requirements.txt found for {app.name}", app_id=app.id)
                if on_log:
                    on_log("No requirements.txt found, skipping dependency install.")

            # Create persistent data directory (survives upgrades, injected as APP_DATA_DIR)
            data_dir = self._get_app_dir(app.name) / "data"
            data_dir.mkdir(parents=True, exist_ok=True)

            # Update state
            app.state = AppState.INSTALLED
            session.add(app)

            logger.info(f"App {app.name} installed successfully", app_id=app.id)
            if on_log:
                on_log(f"App {app.name} installed successfully.")

    def enable_app(self, app_id: int) -> None:
        """Enable an app."""
        is_perpetual = False

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.can_enable:
                raise ValueError(f"App {app.name} cannot be enabled from state {app.state}")

            logger.info(f"Enabling app {app.name}", app_id=app.id)

            app.state = AppState.ENABLED
            session.add(app)
            is_perpetual = app.app_type == AppType.PERPETUAL
            app_name = app.name  # extract before session commits and expires attributes

        # Start AFTER the session commits ENABLED — otherwise the commit overwrites RUNNING.
        # start_app takes an int app_id; never pass the ORM object as it is
        # expired+detached by the time we get here (session committed and closed above).
        if is_perpetual:
            self.supervisor.start_app(app_id)

        logger.info(f"App {app_name} enabled", app_id=app_id)

    def disable_app(self, app_id: int) -> None:
        """Disable an app."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.can_disable:
                raise ValueError(f"App {app.name} cannot be disabled from state {app.state}")

            logger.info(f"Disabling app {app.name}", app_id=app.id)

            # Stop if running
            if app.state == AppState.RUNNING:
                self.supervisor.stop_app(app)

            app.state = AppState.DISABLED
            session.add(app)

            logger.info(f"App {app.name} disabled", app_id=app.id)

    # -- updates ----------------------------------------------------------
    #
    # Both update paths follow the same order so a failure never leaves the app
    # half-updated: stage the new source in a temp dir, install its requirements
    # into the venv, and only then swap it in for the live source. Until the swap
    # succeeds the live source is untouched, so rollback is just "don't swap" plus
    # restarting the app if we stopped it.

    def _staging_dir(self, app_name: str) -> Path:
        """Fresh temp directory for staging an app's new source."""
        staging_dir = self.settings.temp_dir / f"{app_name}_update"
        if staging_dir.exists():
            # Leftover from an interrupted update; never mix it into this one.
            shutil.rmtree(staging_dir)
        staging_dir.parent.mkdir(parents=True, exist_ok=True)
        return staging_dir

    def _stop_for_update(self, app_id: int) -> None:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if app:
                self.supervisor.stop_app(app)

    def _install_staged_requirements(
        self, app_name: str, staging_dir: Path, on_log: LogCallback | None
    ) -> None:
        """Install the *new* source's requirements before it goes live."""
        requirements_file = staging_dir / "requirements.txt"
        if requirements_file.exists():
            logger.info(f"Installing dependencies for {app_name} from staged source")
            self.venv_manager.install_requirements(app_name, requirements_file, on_log=on_log)
        else:
            logger.info(f"No requirements.txt found for {app_name}")
            if on_log:
                on_log("No requirements.txt found, skipping dependency install.")

    def _swap_in_source(self, source_dir: Path, staging_dir: Path) -> Path | None:
        """Replace the live source with the staged one.

        The old source is renamed aside rather than deleted, and returned so the
        caller can restore it (_swap_back) or discard it once the update commits.
        """
        previous_dir = source_dir.with_name(f"{source_dir.name}.previous")
        if previous_dir.exists():
            shutil.rmtree(previous_dir)

        if source_dir.exists():
            source_dir.rename(previous_dir)
        else:
            previous_dir = None

        try:
            shutil.move(str(staging_dir), str(source_dir))
        except Exception:
            # A cross-filesystem move may have left a partial copy behind.
            if source_dir.exists():
                shutil.rmtree(source_dir)
            if previous_dir is not None:
                previous_dir.rename(source_dir)
            raise

        return previous_dir

    def _swap_back(self, source_dir: Path, previous_dir: Path | None) -> None:
        """Undo _swap_in_source, putting the previous source back in place."""
        if previous_dir is None:
            return
        if source_dir.exists():
            shutil.rmtree(source_dir)
        previous_dir.rename(source_dir)

    def _restart_after_failed_update(
        self, app_id: int, app_name: str, on_log: LogCallback | None
    ) -> None:
        """Best-effort restart of the previous version after a failed update."""
        logger.info(f"Restarting {app_name} on its previous version after failed update")
        if on_log:
            on_log(f"Restarting {app_name} on its previous version...")
        try:
            self.supervisor.start_app(app_id)
        except Exception as e:
            logger.error(f"Failed to restart {app_name} after failed update: {e}", app_id=app_id)
            if on_log:
                on_log(f"Failed to restart {app_name}: {e}")

    @staticmethod
    def _next_version(current: str, old_version: str) -> str:
        version_parts = current.split(".")
        if len(version_parts) == 3:
            version_parts[-1] = str(int(version_parts[-1]) + 1)
        else:
            version_parts = [old_version, "1"]
        return ".".join(version_parts)

    def update_app_from_zip(
        self,
        app_id: int,
        zip_path: Path,
        backup: bool = True,
        on_log: LogCallback | None = None,
    ) -> dict[str, Any]:
        """Update an app from a ZIP archive while preserving configuration.

        On failure the previous source stays live, the version is unchanged, and
        the app is restarted if it was running.
        """
        logger.info(f"Updating app {app_id} from ZIP: {zip_path}")

        self._validate_upload(zip_path)

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if app.is_deleted:
                raise ValueError(f"Cannot update deleted app {app.name}")

            app_name = app.name
            was_running = app.state == AppState.RUNNING
            old_version = app.version

        source_dir = self._get_app_source_dir(app_name)
        staging_dir = self._staging_dir(app_name)
        stopped = False

        try:
            if was_running:
                self._stop_for_update(app_id)
                stopped = True

            if backup:
                backup_dir = self._backup_app(app_name)
                logger.info(f"Created backup at {backup_dir}")

            # Extract new source to the staging directory
            staging_dir.mkdir(parents=True)
            if on_log:
                on_log(f"Extracting {zip_path.name}...")

            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                # Security: check for path traversal
                for member in zip_ref.namelist():
                    if member.startswith("/") or ".." in member:
                        raise ValueError(f"Invalid path in ZIP: {member}")
                zip_ref.extractall(staging_dir)

            new_entrypoint = self._detect_entrypoint(staging_dir)

            self._install_staged_requirements(app_name, staging_dir, on_log)

            previous_dir = self._swap_in_source(source_dir, staging_dir)
            try:
                with get_db() as session:
                    app = session.query(App).filter(App.id == app_id).first()
                    app.version = self._next_version(app.version, old_version)
                    app.entrypoint = new_entrypoint
                    app.last_updated_at = datetime.now()
                    app.update_count += 1
                    session.add(app)
                    session.commit()
                    new_version = app.version
            except Exception:
                self._swap_back(source_dir, previous_dir)
                raise

            if previous_dir is not None:
                shutil.rmtree(previous_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Failed to update app {app_name}: {e}", app_id=app_id)
            if on_log:
                on_log(f"Update failed; keeping previous version {old_version}.")
            if stopped:
                self._restart_after_failed_update(app_id, app_name, on_log)
            raise
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

        if was_running:
            self.supervisor.start_app(app_id)
            logger.info(f"Restarted app {app_name} after update")

        logger.info(
            f"App {app_name} updated successfully from {old_version} to {new_version}",
            app_id=app_id,
        )

        return {
            "app_id": app_id,
            "app_name": app_name,
            "old_version": old_version,
            "new_version": new_version,
            "backup_created": backup,
        }

    def pull_git_app(
        self, app_id: int, backup: bool = True, on_log: LogCallback | None = None
    ) -> dict[str, Any]:
        """Pull latest changes from Git repository for an app.

        The pull happens in a staged copy of the repo, so on failure the previous
        checkout stays live, the version is unchanged, and the app is restarted if
        it was running.
        """
        logger.info(f"Pulling Git updates for app {app_id}")

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.git_url:
                raise ValueError(f"App {app.name} is not a Git-based app")

            if app.is_deleted:
                raise ValueError(f"Cannot update deleted app {app.name}")

            app_name = app.name
            git_url = app.git_url
            git_branch = app.git_branch or "main"
            old_commit = app.git_commit
            old_version = app.version
            was_running = app.state == AppState.RUNNING

        source_dir = self._get_app_source_dir(app_name)
        staging_dir = self._staging_dir(app_name)
        stopped = False
        changed = False
        new_version = old_version

        try:
            if was_running:
                self._stop_for_update(app_id)
                stopped = True

            if backup:
                backup_dir = self._backup_app(app_name)
                logger.info(f"Created backup at {backup_dir}")

            # Pull into a copy of the checkout so the live source stays intact
            # until the new dependencies are installed.
            shutil.copytree(source_dir, staging_dir, symlinks=True)

            if on_log:
                on_log(f"Pulling {git_branch} from {git_url}...")
            repo = Repo(staging_dir)
            origin = repo.remotes.origin
            progress = _GitLogProgress(on_log) if on_log else None
            origin.pull(git_branch, progress=progress)

            new_commit = repo.head.commit.hexsha
            repo.close()

            if new_commit == old_commit:
                logger.info(f"No changes detected for {app_name} (commit: {new_commit})")
            else:
                changed = True
                self._install_staged_requirements(app_name, staging_dir, on_log)

                new_entrypoint = self._detect_entrypoint(staging_dir)

                previous_dir = self._swap_in_source(source_dir, staging_dir)
                try:
                    with get_db() as session:
                        app = session.query(App).filter(App.id == app_id).first()
                        if not app:
                            raise ValueError(f"App {app_id} not found")
                        app.version = self._next_version(app.version, old_version)
                        app.git_commit = new_commit
                        app.entrypoint = new_entrypoint
                        app.last_updated_at = datetime.now()
                        app.update_count += 1
                        session.add(app)
                        session.commit()
                        new_version = app.version
                except Exception:
                    self._swap_back(source_dir, previous_dir)
                    raise

                if previous_dir is not None:
                    shutil.rmtree(previous_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Failed to pull Git updates for {app_name}: {e}", app_id=app_id)
            if on_log:
                on_log(f"Update failed; keeping previous version {old_version}.")
            if stopped:
                self._restart_after_failed_update(app_id, app_name, on_log)
            raise
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

        if was_running:
            self.supervisor.start_app(app_id)
            logger.info(f"Restarted app {app_name} after update")

        if changed:
            old_commit_short = old_commit[:8] if old_commit else "unknown"
            logger.info(
                f"App {app_name} updated from commit {old_commit_short} to {new_commit[:8]}",
                app_id=app_id,
            )

        return {
            "app_id": app_id,
            "app_name": app_name,
            "old_version": old_version,
            "new_version": new_version,
            "old_commit": old_commit or "",
            "new_commit": new_commit,
            "changed": changed,
            "backup_created": backup,
        }

    def rebuild_app_venv(self, app_id: int, on_log: LogCallback | None = None) -> dict[str, Any]:
        """Delete and recreate an app's venv, then reinstall its requirements.

        The app is stopped for the rebuild and restarted afterwards if it was
        running. If the rebuild fails the app is left stopped, since it can't run
        without a working environment.
        """
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")
            if app.is_deleted:
                raise ValueError(f"Cannot rebuild environment for deleted app {app.name}")

            app_name = app.name
            was_running = app.state == AppState.RUNNING

        if was_running:
            if on_log:
                on_log(f"Stopping {app_name}...")
            self._stop_for_update(app_id)

        requirements_file = self._get_app_source_dir(app_name) / "requirements.txt"
        try:
            self.venv_manager.rebuild(
                app_name,
                requirements_file if requirements_file.exists() else None,
                on_log=on_log,
            )
        except Exception as e:
            logger.error(f"Failed to rebuild venv for {app_name}: {e}", app_id=app_id)
            if on_log and was_running:
                on_log(f"Rebuild failed; {app_name} has been left stopped.")
            raise

        if was_running:
            if on_log:
                on_log(f"Restarting {app_name}...")
            self.supervisor.start_app(app_id)

        logger.info(f"Rebuilt virtual environment for {app_name}", app_id=app_id)
        if on_log:
            on_log("Environment rebuilt.")
        return {"app_id": app_id, "app_name": app_name}

    def check_git_update(self, app_id: int) -> dict[str, Any]:
        """Check whether the remote Git repository has new commits without modifying local files."""
        logger.info(f"Checking for Git updates for app {app_id}")

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.git_url:
                raise ValueError(f"App {app.name} is not a Git-based app")

            if app.is_deleted:
                raise ValueError(f"Cannot check deleted app {app.name}")

            app_name = app.name
            git_branch = app.git_branch or "main"

        source_dir = self._get_app_source_dir(app_name)

        try:
            repo = Repo(source_dir)
            origin = repo.remotes.origin
            origin.fetch()

            # Use the actual checked-out commit from disk (not the possibly-stale DB value)
            local_commit = repo.head.commit.hexsha

            # Resolve the remote tracking ref (e.g. "origin/main")
            try:
                remote_commit = repo.commit(f"origin/{git_branch}").hexsha
            except git_exc.BadName:
                raise ValueError(f"Remote branch '{git_branch}' not found after fetch")

            # Count commits that are in origin/<branch> but not in the local HEAD.
            # This is >0 when the remote is strictly ahead, and stays 0 if local is
            # ahead or diverged — both of which don't need a pull from the user's POV.
            if local_commit:
                remote_ahead_count = int(
                    repo.git.rev_list("--count", f"{local_commit}..{remote_commit}")
                )
                update_available = remote_ahead_count > 0
            else:
                update_available = True

            logger.info(
                f"Git check for {app_name}: local={local_commit[:8] if local_commit else 'unknown'} "
                f"remote={remote_commit[:8]} update_available={update_available}",
                app_id=app_id,
            )

            return {
                "app_id": app_id,
                "app_name": app_name,
                "update_available": update_available,
                "local_commit": local_commit,
                "remote_commit": remote_commit,
            }

        except ValueError:
            raise
        except Exception as e:
            logger.error(f"Failed to check Git updates for {app_name}: {e}", app_id=app_id)
            raise

    def _backup_app(self, app_name: str) -> Path:
        """Create a backup of an app."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.settings.backups_dir / app_name / timestamp
        # Two updates within the same second would otherwise collide.
        suffix = 1
        while backup_dir.exists():
            backup_dir = self.settings.backups_dir / app_name / f"{timestamp}_{suffix}"
            suffix += 1
        backup_dir.mkdir(parents=True)

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

            logger.info(f"Deleting app {app.name} (soft={soft})", app_id=app.id)

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
