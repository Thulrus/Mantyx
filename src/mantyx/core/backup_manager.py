"""
Full-instance backup and restore.

Exports/imports everything needed to reconstruct a Mantyx instance: the
database (apps, schedules, executions, logs, settings) and each app's source
+ persistent data. Virtual environments are intentionally excluded — they're
rebuilt from each app's requirements.txt on restore, the same way
AppManager.update_app_from_zip() reinstalls dependencies after an update.
"""

import json
import shutil
import sqlite3
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from mantyx import __version__
from mantyx.config import get_settings
from mantyx.core.supervisor import ProcessSupervisor
from mantyx.core.venv_manager import VenvManager
from mantyx.database import dispose_engine, get_db, init_db
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState

LogCallback = Callable[[str], None]

logger = get_logger("backup_manager")

MANIFEST_NAME = "manifest.json"
DATABASE_NAME = "database.db"
APPS_PREFIX = "apps"
CONFIG_PREFIX = "config"


class BackupManager:
    """Creates and restores full-instance backup archives."""

    def __init__(self, venv_manager: VenvManager | None = None):
        self.settings = get_settings()
        self.venv_manager = venv_manager or VenvManager()

    def _validate_sqlite_backend(self) -> None:
        """Backups only support the default SQLite backend for now."""
        if not self.settings.effective_database_url.startswith("sqlite:///"):
            raise ValueError(
                "Backup and restore are only supported with the default SQLite " "database backend."
            )

    def create_backup(self, on_log: LogCallback | None = None) -> Path:
        """Create a full backup archive and return its path.

        The caller owns the returned file (e.g. to stream it to a client)
        and is responsible for deleting it when done.
        """
        log = on_log or (lambda _msg: None)
        self._validate_sqlite_backend()

        self.settings.temp_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = self.settings.temp_dir / f"mantyx-backup-{timestamp}.zip"
        db_snapshot_path = self.settings.temp_dir / f".backup-db-snapshot-{timestamp}.db"

        with get_db() as session:
            app_count = session.query(App).filter(App.is_deleted == False).count()  # noqa: E712

        log("Snapshotting database...")
        self._snapshot_sqlite_db(self.settings.db_path, db_snapshot_path)

        manifest = {
            "mantyx_version": __version__,
            "created_at": datetime.now().isoformat(),
            "app_count": app_count,
        }

        try:
            log("Building backup archive...")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.writestr(MANIFEST_NAME, json.dumps(manifest, indent=2))
                zf.write(db_snapshot_path, DATABASE_NAME)
                self._add_tree_to_zip(zf, self.settings.apps_dir, APPS_PREFIX)
                self._add_tree_to_zip(zf, self.settings.config_dir, CONFIG_PREFIX)

            logger.info(f"Created backup archive at {zip_path} ({app_count} apps)")
            log("Backup created successfully.")
            return zip_path
        finally:
            db_snapshot_path.unlink(missing_ok=True)

    def restore_backup(self, zip_path: Path, on_log: LogCallback | None = None) -> dict[str, Any]:
        """Restore a backup archive, fully replacing the current instance state.

        This is destructive: it stops the scheduler and all running apps,
        wipes the current database and app/venv directories, replaces them
        with the archive's contents, rebuilds each app's venv, and restarts
        whatever was running before.
        """
        log = on_log or (lambda _msg: None)
        self._validate_sqlite_backend()

        log("Validating backup archive...")
        manifest = self._validate_archive(zip_path)
        logger.info(f"Restoring backup created at {manifest.get('created_at', 'unknown time')}")

        # Lazy import: mantyx.app mounts the router that imports this module,
        # so importing it at module scope would be circular.
        import mantyx.app as mantyx_app
        from mantyx.core import runtime

        log("Stopping scheduler...")
        old_scheduler = runtime.get_scheduler() or mantyx_app.scheduler
        if old_scheduler is not None:
            old_scheduler.stop()

        log("Stopping running apps...")
        supervisor = runtime.get_supervisor()
        with get_db() as session:
            running_apps = session.query(App).filter(App.state == AppState.RUNNING).all()
            session.expunge_all()
        for app in running_apps:
            try:
                supervisor.stop_app(app)
            except Exception as e:
                logger.warning(f"Failed to stop app {app.name} before restore: {e}")
                log(f"Warning: failed to stop {app.name}: {e}")

        log("Closing database connection...")
        dispose_engine()

        extract_dir = (
            self.settings.temp_dir / f".restore-{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        )
        try:
            log("Extracting backup archive...")
            self._extract_archive(zip_path, extract_dir)

            log("Replacing application files...")
            self._replace_apps_and_venvs(extract_dir)
            self._replace_config(extract_dir)
            self._replace_database(extract_dir)

            log("Reinitializing database...")
            init_db()

            log("Rebuilding virtual environments...")
            venv_errors = self._rebuild_venvs(on_log)

            from mantyx.core.scheduler import AppScheduler

            new_supervisor = ProcessSupervisor()
            new_scheduler = AppScheduler()
            runtime.set_runtime(scheduler=new_scheduler, supervisor=new_supervisor)
            mantyx_app.scheduler = new_scheduler
            mantyx_app.supervisor = new_supervisor

            log("Restarting apps...")
            new_supervisor.reconcile_on_startup()
            new_supervisor.adopt_running_apps()
            new_scheduler.start()

            with get_db() as session:
                restored_app_count = (
                    session.query(App).filter(App.is_deleted == False).count()  # noqa: E712
                )

            log("Restore complete.")
            return {
                "app_count": restored_app_count,
                "venv_errors": venv_errors,
            }
        finally:
            if extract_dir.exists():
                shutil.rmtree(extract_dir)

    # -- helpers ----------------------------------------------------------

    def _snapshot_sqlite_db(self, src_path: Path, dest_path: Path) -> None:
        """Take a consistent snapshot of a live SQLite DB via the backup API.

        Safer than a raw file copy since it won't race a concurrent writer
        mid-transaction.
        """
        src_conn = sqlite3.connect(str(src_path))
        try:
            dest_conn = sqlite3.connect(str(dest_path))
            try:
                src_conn.backup(dest_conn)
            finally:
                dest_conn.close()
        finally:
            src_conn.close()

    def _add_tree_to_zip(self, zf: zipfile.ZipFile, root: Path, arc_prefix: str) -> None:
        if not root.exists():
            return
        for file_path in root.rglob("*"):
            if file_path.is_file():
                arcname = f"{arc_prefix}/{file_path.relative_to(root).as_posix()}"
                zf.write(file_path, arcname)

    def _validate_archive(self, zip_path: Path) -> dict[str, Any]:
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            if MANIFEST_NAME not in names or DATABASE_NAME not in names:
                raise ValueError("Invalid backup archive: missing manifest.json or database.db")
            for member in names:
                if member.startswith("/") or ".." in member:
                    raise ValueError(f"Invalid path in backup archive: {member}")
            return json.loads(zf.read(MANIFEST_NAME))

    def _extract_archive(self, zip_path: Path, extract_dir: Path) -> None:
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_dir)

    def _replace_apps_and_venvs(self, extract_dir: Path) -> None:
        if self.settings.apps_dir.exists():
            shutil.rmtree(self.settings.apps_dir)
        if self.settings.venvs_dir.exists():
            shutil.rmtree(self.settings.venvs_dir)
        self.settings.venvs_dir.mkdir(parents=True, exist_ok=True)

        extracted_apps = extract_dir / APPS_PREFIX
        if extracted_apps.exists():
            shutil.move(str(extracted_apps), str(self.settings.apps_dir))
        else:
            self.settings.apps_dir.mkdir(parents=True, exist_ok=True)

    def _replace_config(self, extract_dir: Path) -> None:
        extracted_config = extract_dir / CONFIG_PREFIX
        if not extracted_config.exists():
            return
        if self.settings.config_dir.exists():
            shutil.rmtree(self.settings.config_dir)
        shutil.move(str(extracted_config), str(self.settings.config_dir))

    def _replace_database(self, extract_dir: Path) -> None:
        self.settings.data_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(str(extract_dir / DATABASE_NAME), str(self.settings.db_path))

    def _rebuild_venvs(self, on_log: LogCallback | None) -> list[dict[str, str]]:
        with get_db() as session:
            restored_apps = session.query(App).filter(App.is_deleted == False).all()  # noqa: E712
            session.expunge_all()

        errors: list[dict[str, str]] = []
        for app in restored_apps:
            try:
                source_dir = self.settings.apps_dir / app.name / "app"
                requirements_file = source_dir / "requirements.txt"

                self.venv_manager.create(app.name, on_log=on_log)
                if requirements_file.exists():
                    self.venv_manager.install_requirements(
                        app.name, requirements_file, on_log=on_log
                    )
            except Exception as e:
                logger.error(f"Failed to rebuild venv for {app.name}: {e}")
                errors.append({"app": app.name, "error": str(e)})

        return errors
