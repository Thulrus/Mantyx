"""
Application manager handling full app lifecycle.

Coordinates uploads, installations, updates, rollbacks, and deletions.
"""

import json
import re
import shutil
import threading
import zipfile
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from git import RemoteProgress, Repo
from git import exc as git_exc

from mantyx.config import get_settings
from mantyx.core.supervisor import ProcessSupervisor
from mantyx.core.venv_manager import VenvManager
from mantyx.database import get_db
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState, AppType

LogCallback = Callable[[str], None]

logger = get_logger("app_manager")

# App ids become directory names, so keep them to a safe, URL-friendly charset.
APP_NAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
ENTRYPOINT_CANDIDATES = ["main.py", "app.py", "__main__.py", "run.py", "start.py"]
BACKUP_METADATA = "backup.json"
# Directories never offered as entrypoint locations.
_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", ".mypy_cache"}

# Cached results of "is there a newer commit?" checks, keyed by app id.
# Filled by check_git_update (from the API or the periodic background job) so
# browsers never trigger network fetches themselves.
_git_status: dict[int, dict[str, Any]] = {}
_git_status_lock = threading.Lock()


def get_git_status(app_id: int) -> dict[str, Any] | None:
    with _git_status_lock:
        status = _git_status.get(app_id)
        return dict(status) if status else None


def _set_git_status(app_id: int, **fields: Any) -> None:
    with _git_status_lock:
        _git_status[app_id] = {"checked_at": datetime.now().isoformat(), **fields}


def validate_app_name(app_name: str) -> None:
    if not APP_NAME_PATTERN.match(app_name or ""):
        raise ValueError(
            "App ID must be 1–64 characters: lowercase letters, numbers, '-' or '_', "
            "starting with a letter or number"
        )


class _GitLogProgress(RemoteProgress):
    """Forwards GitPython clone/pull progress lines to a log callback."""

    def __init__(self, on_log: LogCallback):
        super().__init__()
        self._on_log = on_log

    def update(self, op_code, cur_count, max_count=None, message=""):
        line = self._cur_line
        if line:
            self._on_log(line)


def safe_extract_zip(zip_path: Path, dest: Path) -> None:
    """Extract a ZIP into `dest`, refusing entries that would escape it.

    macOS metadata (__MACOSX/, .DS_Store) is skipped. If everything sits in a
    single top-level folder with no Python files beside it (what you get from
    "compress this folder"), that folder's contents are moved up to `dest`.
    """
    dest.mkdir(parents=True, exist_ok=True)
    dest_root = dest.resolve()
    with zipfile.ZipFile(zip_path, "r") as zf:
        members = []
        for info in zf.infolist():
            name = info.filename
            parts = Path(name).parts
            if name.startswith("__MACOSX/") or (parts and parts[-1] == ".DS_Store"):
                continue
            target = (dest / name).resolve()
            if name.startswith("/") or (target != dest_root and dest_root not in target.parents):
                raise ValueError(f"Invalid path in ZIP: {name}")
            members.append(info)
        zf.extractall(dest, members=members)

    entries = [p for p in dest.iterdir() if p.name not in {"__MACOSX", ".DS_Store"}]
    if len(entries) == 1 and entries[0].is_dir() and not any(dest.glob("*.py")):
        inner = entries[0]
        tmp = dest / f".flatten-{inner.name}"
        inner.rename(tmp)
        for child in tmp.iterdir():
            child.rename(dest / child.name)
        tmp.rmdir()


def detect_entrypoint(source_dir: Path, preferred: str | None = None) -> str:
    """Pick the file Mantyx runs.

    A previously chosen entrypoint wins if it still exists (so updates keep a
    user's choice), then the conventional names, then a lone .py file or the
    one with an `if __name__ == "__main__"` block.
    """
    if preferred and (source_dir / preferred).is_file():
        return preferred

    for candidate in ENTRYPOINT_CANDIDATES:
        if (source_dir / candidate).is_file():
            return candidate

    py_files = sorted(p for p in source_dir.glob("*.py") if p.is_file())
    if len(py_files) == 1:
        return py_files[0].name
    for path in py_files:
        try:
            if "__main__" in path.read_text(errors="ignore"):
                return path.name
        except OSError:
            continue
    if py_files:
        return py_files[0].name

    raise ValueError(
        "No Python entrypoint found. Put main.py (or another .py file) at the top level "
        "of the ZIP or repository."
    )


class AppManager:
    """Manages application lifecycle operations."""

    def __init__(
        self,
        venv_manager: VenvManager | None = None,
        supervisor: ProcessSupervisor | None = None,
        scheduler=None,
    ):
        from mantyx.core import runtime

        self.settings = get_settings()
        self.venv_manager = venv_manager or VenvManager()
        self.supervisor = supervisor or runtime.get_supervisor()
        # May be None outside the server (e.g. scripts); scheduling calls no-op then.
        self.scheduler = scheduler if scheduler is not None else runtime.get_scheduler()

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
        if not zipfile.is_zipfile(file_path):
            raise ValueError("The uploaded file is not a valid ZIP archive")

    # -- creation -----------------------------------------------------------

    def _prepare_name_slot(self, app_name: str) -> None:
        """Make sure nothing left over from an old app with this ID can leak in.

        A live app with the name is an error. A soft-deleted one (from older
        Mantyx versions) is purged. Files on disk with no app record at all are
        moved into the backups folder rather than deleted.
        """
        validate_app_name(app_name)
        with get_db() as session:
            existing = session.query(App).filter(App.name == app_name).first()
            if existing and not existing.is_deleted:
                raise ValueError(f"An app with the ID '{app_name}' already exists")
            had_record = existing is not None
            if existing:
                session.delete(existing)

        app_dir = self._get_app_dir(app_name)
        if app_dir.exists():
            if had_record:
                shutil.rmtree(app_dir, ignore_errors=True)
            else:
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                target = self.settings.backups_dir / app_name / f"orphaned-{stamp}"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(app_dir), str(target))
                logger.warning(f"Moved leftover files for '{app_name}' to {target}")
        if self.venv_manager.get_venv_path(app_name).exists():
            self.venv_manager.remove(app_name)

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
            on_log(f"Checking {zip_path.name}...")

        self._validate_upload(zip_path)
        self._prepare_name_slot(app_name)

        app_dir = self._get_app_dir(app_name)
        source_dir = self._get_app_source_dir(app_name)

        try:
            if on_log:
                on_log("Extracting files...")
            safe_extract_zip(zip_path, source_dir)

            entrypoint = detect_entrypoint(source_dir)
            if on_log:
                on_log(f"Entrypoint: {entrypoint}")
                has_reqs = (source_dir / "requirements.txt").exists()
                on_log("Found requirements.txt" if has_reqs else "No requirements.txt found")

            app_id = self._insert_app(
                name=app_name,
                display_name=display_name,
                description=description,
                app_type=app_type,
                entrypoint=entrypoint,
            )
            logger.info(f"Added {display_name}", app_id=app_id)
            return {"id": app_id, "name": app_name}

        except Exception as e:
            if app_dir.exists():
                shutil.rmtree(app_dir, ignore_errors=True)
            logger.error(f"Failed to create app from ZIP: {e}")
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
        branch = (branch or "main").strip()
        self._prepare_name_slot(app_name)
        if on_log:
            on_log(f"Cloning {git_url} (branch {branch})...")

        source_dir = self._get_app_source_dir(app_name)

        try:
            source_dir.parent.mkdir(parents=True, exist_ok=True)
            progress = _GitLogProgress(on_log) if on_log else None
            repo = Repo.clone_from(git_url, source_dir, branch=branch, progress=progress)
            commit_hash = repo.head.commit.hexsha
            repo.close()
            if on_log:
                on_log(f"Cloned at commit {commit_hash[:8]}.")

            entrypoint = detect_entrypoint(source_dir)
            if on_log:
                on_log(f"Entrypoint: {entrypoint}")

            app_id = self._insert_app(
                name=app_name,
                display_name=display_name,
                description=description,
                app_type=app_type,
                entrypoint=entrypoint,
                git_url=git_url,
                git_branch=branch,
                git_commit=commit_hash,
            )
            _set_git_status(
                app_id, update_available=False, local_commit=commit_hash, remote_commit=commit_hash
            )
            logger.info(f"Added {display_name} from {git_url}", app_id=app_id)
            return {"id": app_id, "name": app_name}

        except Exception as e:
            if self._get_app_dir(app_name).exists():
                shutil.rmtree(self._get_app_dir(app_name), ignore_errors=True)
            logger.error(f"Failed to create app from Git: {e}")
            if isinstance(e, git_exc.GitCommandError):
                raise RuntimeError(
                    f"Couldn't clone the repository. Check the URL and branch name "
                    f"and that the server can reach it. ({e.stderr.strip() if e.stderr else e})"
                ) from e
            raise

    def _insert_app(self, **fields: Any) -> int:
        app = App(state=AppState.UPLOADED, version="1.0.0", **fields)
        with get_db() as session:
            session.add(app)
            session.flush()
            return app.id

    def _detect_entrypoint(self, source_dir: Path) -> str:
        """Backward-compatible wrapper."""
        return detect_entrypoint(source_dir)

    # -- install / enable / start --------------------------------------------

    def install_app(self, app_id: int, on_log: LogCallback | None = None) -> None:
        """Install an app's dependencies into its own virtual environment."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")
            if app.state != AppState.UPLOADED:
                raise ValueError(f"App {app.name} is already installed")
            app_name = app.name

        logger.info(f"Installing dependencies for {app_name}", app_id=app_id)

        requirements_file = self._get_app_source_dir(app_name) / "requirements.txt"
        if requirements_file.exists():
            self.venv_manager.install_requirements(app_name, requirements_file, on_log=on_log)
        else:
            self.venv_manager.ensure_healthy(app_name, on_log=on_log)
            if on_log:
                on_log("No requirements.txt found, so there are no dependencies to install.")

        # Persistent data directory (survives upgrades, injected as APP_DATA_DIR)
        (self._get_app_dir(app_name) / "data").mkdir(parents=True, exist_ok=True)

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if app and app.state == AppState.UPLOADED:
                app.state = AppState.INSTALLED

        logger.info(f"Installed {app_name}", app_id=app_id)
        if on_log:
            on_log("Dependencies installed.")

    def enable_app(self, app_id: int) -> None:
        """Enable an app (scheduled: schedules start firing; perpetual: start it)."""
        is_perpetual = False

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")
            if app.state == AppState.UPLOADED:
                raise ValueError(f"Install {app.name} before activating it")
            if not app.can_enable:
                raise ValueError(f"App {app.name} cannot be enabled from state {app.state.value}")

            app.state = AppState.ENABLED
            is_perpetual = app.app_type == AppType.PERPETUAL
            app_name = app.name

        # Start AFTER the session commits ENABLED — otherwise the commit overwrites RUNNING.
        if is_perpetual:
            self.supervisor.start_app(app_id)

        logger.info(f"{app_name} activated", app_id=app_id)

    def disable_app(self, app_id: int) -> None:
        """Disable an app (stops it, and its schedules stop firing)."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            if not app.can_disable:
                raise ValueError(f"App {app.name} cannot be paused from state {app.state.value}")

            if app.state == AppState.RUNNING:
                self.supervisor.stop_app(app)

            app_name = app.name

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if app:
                app.state = AppState.DISABLED

        logger.info(f"{app_name} paused", app_id=app_id)

    def start_app(self, app_id: int) -> None:
        """Start a perpetual app, activating it first if needed."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app or app.is_deleted:
                raise ValueError("App not found")
            if app.app_type != AppType.PERPETUAL:
                raise ValueError("Only always-running apps can be started; use Run now instead")
            if app.state == AppState.UPLOADED:
                raise ValueError(f"Install {app.name} before starting it")
            if app.state in (AppState.INSTALLED, AppState.DISABLED):
                app.state = AppState.ENABLED
        self.supervisor.start_app(app_id)

    def stop_app(self, app_id: int) -> None:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError("App not found")
            if app.state != AppState.RUNNING:
                # Already not running; make sure it won't auto-start at boot either.
                if app.app_type == AppType.PERPETUAL and app.state in (
                    AppState.ENABLED,
                    AppState.FAILED,
                ):
                    app.state = AppState.STOPPED
                return
            self.supervisor.stop_app(app)

    def restart_app(self, app_id: int) -> None:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError("App not found")
            if app.app_type != AppType.PERPETUAL:
                raise ValueError("Only always-running apps can be restarted")
            if app.state == AppState.UPLOADED:
                raise ValueError(f"Install {app.name} before starting it")
            if app.state in (AppState.INSTALLED, AppState.DISABLED):
                app.state = AppState.ENABLED
        self.supervisor.restart_app(app_id)

    def provision_app(
        self,
        app_id: int,
        *,
        schedule: dict | None = None,
        activate: bool = True,
        on_log: LogCallback | None = None,
        on_step: Callable[[str, str], None] | None = None,
    ) -> dict[str, Any]:
        """Finish setting up a freshly added app: install, schedule, activate.

        Each phase reports through on_step(key, status) so the UI can show a
        checklist. If installing fails the app is left "Not installed" and can
        be retried from the UI.
        """
        step = on_step or (lambda _k, _s: None)

        step("install", "running")
        self.install_app(app_id, on_log=on_log)
        step("install", "done")

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            is_scheduled = app.app_type == AppType.SCHEDULED

        if is_scheduled and schedule:
            step("schedule", "running")
            self.create_schedule(app_id, schedule)
            if on_log:
                on_log(f"Schedule '{schedule.get('name') or 'Schedule'}' added.")
            step("schedule", "done")
        elif is_scheduled:
            step("schedule", "skipped")

        if activate:
            step("activate", "running")
            if is_scheduled:
                self.enable_app(app_id)
                if on_log:
                    on_log("Activated: it will now run on its schedule.")
            else:
                self.start_app(app_id)
                if on_log:
                    on_log("Started.")
            step("activate", "done")
        else:
            step("activate", "skipped")

        return {"app_id": app_id}

    def create_schedule(self, app_id: int, data: dict) -> int:
        """Validate and save a schedule, and register it with the scheduler."""
        from mantyx.core.scheduler import build_trigger, get_effective_timezone
        from mantyx.models.schedule import Schedule

        schedule_type = data.get("schedule_type")
        build_trigger(
            schedule_type,
            data.get("cron_expression"),
            data.get("interval_seconds"),
            get_effective_timezone(),
        )
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app or app.is_deleted:
                raise ValueError("App not found")
            if app.app_type != AppType.SCHEDULED:
                raise ValueError("Schedules can only be added to scheduled apps")
            schedule = Schedule(
                app_id=app_id,
                name=(data.get("name") or "Schedule").strip() or "Schedule",
                description=data.get("description"),
                schedule_type=schedule_type,
                cron_expression=data.get("cron_expression") if schedule_type == "cron" else None,
                interval_seconds=(
                    data.get("interval_seconds") if schedule_type == "interval" else None
                ),
                timezone=get_effective_timezone(),
                timeout_seconds=data.get("timeout_seconds"),
                is_enabled=data.get("is_enabled", True),
            )
            session.add(schedule)
            session.flush()
            schedule_id = schedule.id
            if schedule.is_enabled and self.scheduler is not None:
                self.scheduler.add_schedule(schedule)
        return schedule_id

    # -- updates ----------------------------------------------------------
    #
    # Every update path follows the same order so a failure never leaves the
    # app half-updated: prepare and validate the new source in a staging dir
    # while the app keeps running, then stop it, back up the live source,
    # install the new requirements, and only then swap the new source in.
    # Until the swap succeeds the live source is untouched, so rollback is just
    # "don't swap" plus restarting the app if we stopped it.

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
            self.supervisor.start_app(app_id, trigger_type="update")
        except Exception as e:
            logger.error(f"Failed to restart {app_name} after failed update: {e}", app_id=app_id)
            if on_log:
                on_log(f"Failed to restart {app_name}: {e}")

    @staticmethod
    def _next_version(current: str, old_version: str) -> str:
        version_parts = current.split(".")
        if len(version_parts) == 3 and version_parts[-1].isdigit():
            version_parts[-1] = str(int(version_parts[-1]) + 1)
        else:
            version_parts = [old_version, "1"]
        return ".".join(version_parts)

    def _load_for_update(self, app_id: int, require_git: bool = False) -> dict[str, Any]:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")
            if app.is_deleted:
                raise ValueError(f"Cannot update deleted app {app.name}")
            if require_git and not app.git_url:
                raise ValueError(f"App {app.name} is not a Git-based app")
            return {
                "name": app.name,
                "was_running": app.state == AppState.RUNNING,
                "version": app.version,
                "entrypoint": app.entrypoint,
                "git_url": app.git_url,
                "git_branch": app.git_branch or "main",
                "git_commit": app.git_commit,
            }

    def _apply_staged_source(
        self,
        app_id: int,
        info: dict[str, Any],
        staging_dir: Path,
        *,
        backup: bool,
        reason: str,
        apply_fields: Callable[[App], None],
        on_log: LogCallback | None,
    ) -> str:
        """Stop → back up → install → swap → record → restart. Returns the new version."""
        app_name = info["name"]
        source_dir = self._get_app_source_dir(app_name)
        stopped = False
        try:
            if info["was_running"]:
                if on_log:
                    on_log(f"Stopping {app_name}...")
                self._stop_for_update(app_id)
                stopped = True

            if backup:
                backup_dir = self._backup_app(app_name, info, reason=reason)
                if on_log:
                    on_log(f"Saved a backup of version {info['version']}.")
                logger.info(f"Created backup at {backup_dir}")

            self._install_staged_requirements(app_name, staging_dir, on_log)

            previous_dir = self._swap_in_source(source_dir, staging_dir)
            try:
                with get_db() as session:
                    app = session.query(App).filter(App.id == app_id).first()
                    if not app:
                        raise ValueError(f"App {app_id} not found")
                    apply_fields(app)
                    app.last_updated_at = datetime.now()
                    app.update_count = (app.update_count or 0) + 1
                    session.flush()
                    new_version = app.version
            except Exception:
                self._swap_back(source_dir, previous_dir)
                raise

            if previous_dir is not None:
                shutil.rmtree(previous_dir, ignore_errors=True)

        except Exception as e:
            logger.error(f"Failed to update {app_name}: {e}", app_id=app_id)
            if on_log:
                on_log(f"Update failed; keeping previous version {info['version']}.")
            if stopped:
                self._restart_after_failed_update(app_id, app_name, on_log)
            raise
        finally:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)

        if info["was_running"]:
            if on_log:
                on_log(f"Starting {app_name}...")
            self.supervisor.start_app(app_id, trigger_type="update")

        return new_version

    def update_app_from_zip(
        self,
        app_id: int,
        zip_path: Path,
        backup: bool = True,
        on_log: LogCallback | None = None,
    ) -> dict[str, Any]:
        """Update an app from a ZIP archive while preserving configuration and data.

        On failure the previous source stays live, the version is unchanged, and
        the app is restarted if it was running.
        """
        logger.info(f"Updating app {app_id} from ZIP: {zip_path}")
        self._validate_upload(zip_path)
        info = self._load_for_update(app_id)
        app_name = info["name"]
        staging_dir = self._staging_dir(app_name)

        try:
            if on_log:
                on_log(f"Extracting {zip_path.name}...")
            safe_extract_zip(zip_path, staging_dir)
            new_entrypoint = detect_entrypoint(staging_dir, preferred=info["entrypoint"])
        except Exception:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            raise

        def apply(app: App) -> None:
            app.version = self._next_version(app.version, info["version"])
            app.entrypoint = new_entrypoint

        new_version = self._apply_staged_source(
            app_id,
            info,
            staging_dir,
            backup=backup,
            reason="Before ZIP update",
            apply_fields=apply,
            on_log=on_log,
        )

        logger.info(
            f"Updated {app_name} from version {info['version']} to {new_version}", app_id=app_id
        )
        return {
            "app_id": app_id,
            "app_name": app_name,
            "old_version": info["version"],
            "new_version": new_version,
            "changed": True,
            "backup_created": backup,
        }

    def pull_git_app(
        self, app_id: int, backup: bool = True, on_log: LogCallback | None = None
    ) -> dict[str, Any]:
        """Pull latest changes from Git repository for an app.

        The pull happens in a staged copy of the repo while the app keeps
        running. If there's nothing new, the app is left alone entirely;
        otherwise it's only stopped once the new code is ready to install.
        """
        logger.info(f"Pulling Git updates for app {app_id}")
        info = self._load_for_update(app_id, require_git=True)
        app_name = info["name"]
        git_branch = info["git_branch"]
        old_commit = info["git_commit"]
        source_dir = self._get_app_source_dir(app_name)
        staging_dir = self._staging_dir(app_name)

        try:
            shutil.copytree(source_dir, staging_dir, symlinks=True)
            if on_log:
                on_log(f"Pulling {git_branch} from {info['git_url']}...")
            repo = Repo(staging_dir)
            try:
                progress = _GitLogProgress(on_log) if on_log else None
                repo.remotes.origin.pull(git_branch, progress=progress)
                new_commit = repo.head.commit.hexsha
            finally:
                repo.close()
        except Exception as e:
            if staging_dir.exists():
                shutil.rmtree(staging_dir)
            logger.error(f"Failed to pull Git updates for {app_name}: {e}", app_id=app_id)
            if isinstance(e, git_exc.GitCommandError):
                raise RuntimeError(f"Git pull failed: {e.stderr.strip() if e.stderr else e}") from e
            raise

        if new_commit == old_commit:
            shutil.rmtree(staging_dir, ignore_errors=True)
            _set_git_status(
                app_id, update_available=False, local_commit=new_commit, remote_commit=new_commit
            )
            if on_log:
                on_log("Already up to date; nothing to do.")
            return {
                "app_id": app_id,
                "app_name": app_name,
                "old_version": info["version"],
                "new_version": info["version"],
                "old_commit": old_commit or "",
                "new_commit": new_commit,
                "changed": False,
                "backup_created": False,
            }

        try:
            new_entrypoint = detect_entrypoint(staging_dir, preferred=info["entrypoint"])
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        def apply(app: App) -> None:
            app.version = self._next_version(app.version, info["version"])
            app.git_commit = new_commit
            app.entrypoint = new_entrypoint

        new_version = self._apply_staged_source(
            app_id,
            info,
            staging_dir,
            backup=backup,
            reason="Before Git update",
            apply_fields=apply,
            on_log=on_log,
        )
        _set_git_status(
            app_id, update_available=False, local_commit=new_commit, remote_commit=new_commit
        )

        logger.info(
            f"Updated {app_name} from commit {(old_commit or 'unknown')[:8]} to {new_commit[:8]}",
            app_id=app_id,
        )
        return {
            "app_id": app_id,
            "app_name": app_name,
            "old_version": info["version"],
            "new_version": new_version,
            "old_commit": old_commit or "",
            "new_commit": new_commit,
            "changed": True,
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

        # An app whose dependencies never installed is now usable.
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if app and app.state == AppState.UPLOADED:
                app.state = AppState.INSTALLED

        if was_running:
            if on_log:
                on_log(f"Restarting {app_name}...")
            self.supervisor.start_app(app_id)

        logger.info(f"Rebuilt the Python environment for {app_name}", app_id=app_id)
        if on_log:
            on_log("Environment rebuilt.")
        return {"app_id": app_id, "app_name": app_name}

    def check_git_update(self, app_id: int) -> dict[str, Any]:
        """Check whether the remote Git repository has new commits without modifying local files."""
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
            try:
                repo.remotes.origin.fetch()
                local_commit = repo.head.commit.hexsha
                try:
                    remote_commit = repo.commit(f"origin/{git_branch}").hexsha
                except git_exc.BadName:
                    raise ValueError(f"Remote branch '{git_branch}' not found after fetch")

                # Commits in origin/<branch> that aren't in HEAD. Stays 0 when local is
                # ahead or diverged — neither needs a pull from the user's point of view.
                behind = int(repo.git.rev_list("--count", f"{local_commit}..{remote_commit}"))
            finally:
                repo.close()

            result = {
                "app_id": app_id,
                "app_name": app_name,
                "update_available": behind > 0,
                "commits_behind": behind,
                "local_commit": local_commit,
                "remote_commit": remote_commit,
            }
            _set_git_status(
                app_id,
                update_available=behind > 0,
                commits_behind=behind,
                local_commit=local_commit,
                remote_commit=remote_commit,
            )
            return result

        except Exception as e:
            _set_git_status(app_id, update_available=None, error=str(e))
            logger.warning(f"Failed to check Git updates for {app_name}: {e}")
            raise

    # -- backups / rollback ---------------------------------------------------

    def _backup_app(
        self, app_name: str, info: dict[str, Any] | None = None, reason: str = ""
    ) -> Path:
        """Copy the live source into a timestamped backup folder (with metadata)."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = self.settings.backups_dir / app_name / timestamp
        # Two updates within the same second would otherwise collide.
        suffix = 1
        while backup_dir.exists():
            backup_dir = self.settings.backups_dir / app_name / f"{timestamp}_{suffix}"
            suffix += 1
        backup_dir.mkdir(parents=True)

        source_dir = self._get_app_source_dir(app_name)
        shutil.copytree(source_dir, backup_dir / "app", symlinks=True)

        info = info or {}
        metadata = {
            "created_at": datetime.now().isoformat(),
            "version": info.get("version"),
            "git_commit": info.get("git_commit"),
            "entrypoint": info.get("entrypoint"),
            "reason": reason,
        }
        (backup_dir / BACKUP_METADATA).write_text(json.dumps(metadata, indent=2))

        from mantyx.core.maintenance import prune_backups

        prune_backups(backup_dir.parent, self.settings.backup_retention_count)
        return backup_dir

    def list_backups(self, app_id: int) -> list[dict[str, Any]]:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError("App not found")
            app_name = app.name

        root = self.settings.backups_dir / app_name
        if not root.is_dir():
            return []
        backups = []
        for entry in sorted(root.iterdir(), key=lambda p: p.name, reverse=True):
            if not entry.is_dir() or not (entry / "app").is_dir():
                continue
            metadata: dict[str, Any] = {}
            meta_path = entry / BACKUP_METADATA
            if meta_path.exists():
                try:
                    metadata = json.loads(meta_path.read_text())
                except (OSError, ValueError):
                    metadata = {}
            created_at = metadata.get("created_at")
            if not created_at:
                try:
                    created_at = datetime.strptime(entry.name[:15], "%Y%m%d_%H%M%S").isoformat()
                except ValueError:
                    created_at = datetime.fromtimestamp(entry.stat().st_mtime).isoformat()
            backups.append(
                {
                    "id": entry.name,
                    "created_at": created_at,
                    "version": metadata.get("version"),
                    "git_commit": metadata.get("git_commit"),
                    "reason": metadata.get("reason")
                    or ("Leftover files" if entry.name.startswith("orphaned") else None),
                }
            )
        return backups

    def restore_app_backup(
        self, app_id: int, backup_id: str, on_log: LogCallback | None = None
    ) -> dict[str, Any]:
        """Roll an app back to one of its saved versions.

        Goes through the same safe path as an update (the current version is
        backed up first), so a rollback can itself be undone.
        """
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", backup_id or "") or backup_id in {".", ".."}:
            raise ValueError("Invalid backup id")

        info = self._load_for_update(app_id)
        app_name = info["name"]
        backup_dir = self.settings.backups_dir / app_name / backup_id
        if not (backup_dir / "app").is_dir():
            raise ValueError("Backup not found")

        metadata: dict[str, Any] = {}
        if (backup_dir / BACKUP_METADATA).exists():
            try:
                metadata = json.loads((backup_dir / BACKUP_METADATA).read_text())
            except (OSError, ValueError):
                metadata = {}

        staging_dir = self._staging_dir(app_name)
        if on_log:
            on_log(f"Preparing saved version from {backup_id}...")
        shutil.copytree(backup_dir / "app", staging_dir, symlinks=True)

        try:
            new_entrypoint = detect_entrypoint(
                staging_dir, preferred=metadata.get("entrypoint") or info["entrypoint"]
            )
        except Exception:
            shutil.rmtree(staging_dir, ignore_errors=True)
            raise

        restored_commit = metadata.get("git_commit")
        if info["git_url"] and (staging_dir / ".git").exists():
            try:
                repo = Repo(staging_dir)
                restored_commit = repo.head.commit.hexsha
                repo.close()
            except Exception:
                pass

        def apply(app: App) -> None:
            app.version = metadata.get("version") or app.version
            app.entrypoint = new_entrypoint
            if app.git_url and restored_commit:
                app.git_commit = restored_commit

        new_version = self._apply_staged_source(
            app_id,
            info,
            staging_dir,
            backup=True,
            reason=f"Before rolling back to {metadata.get('version') or backup_id}",
            apply_fields=apply,
            on_log=on_log,
        )
        if info["git_url"]:
            with _git_status_lock:
                _git_status.pop(app_id, None)

        logger.info(f"Rolled {app_name} back to version {new_version}", app_id=app_id)
        return {"app_id": app_id, "app_name": app_name, "new_version": new_version}

    # -- files ----------------------------------------------------------------

    def list_python_files(self, app_id: int) -> list[str]:
        """Python files (up to two folders deep) that could serve as the entrypoint."""
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError("App not found")
            app_name = app.name
        root = self._get_app_source_dir(app_name)
        if not root.is_dir():
            return []
        found: list[str] = []
        for path in sorted(root.rglob("*.py")):
            rel = path.relative_to(root)
            if len(rel.parts) > 3 or any(part in _SKIP_DIRS for part in rel.parts):
                continue
            found.append(rel.as_posix())
            if len(found) >= 300:
                break
        return found

    def validate_entrypoint(self, app_id: int, entrypoint: str) -> str:
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError("App not found")
            app_name = app.name
        entrypoint = entrypoint.strip()
        root = self._get_app_source_dir(app_name).resolve()
        target = (root / entrypoint).resolve()
        if not entrypoint.endswith(".py") or root not in target.parents:
            raise ValueError("Entrypoint must be a .py file inside the app")
        if not target.is_file():
            raise ValueError(f"File not found in the app: {entrypoint}")
        return target.relative_to(root).as_posix()

    # -- deletion -------------------------------------------------------------

    def delete_app(self, app_id: int, soft: bool = False) -> None:
        """Delete an app.

        By default everything is removed: the database record (with its run
        history and schedules), source, persistent data, environment, logs and
        update backups. soft=True keeps the legacy behaviour of only hiding it.
        """
        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            if not app:
                raise ValueError(f"App {app_id} not found")

            app_name = app.name
            logger.info(f"Deleting app {app_name}", app_id=app_id)

            if app.state == AppState.RUNNING:
                self.supervisor.stop_app(app)

        with get_db() as session:
            app = session.query(App).filter(App.id == app_id).first()
            schedule_ids = [s.id for s in app.schedules]
            if self.scheduler is not None:
                for schedule_id in schedule_ids:
                    self.scheduler.remove_schedule(schedule_id)

            if soft:
                app.is_deleted = True
                app.deleted_at = datetime.now()
                app.state = AppState.DELETED
                for schedule in app.schedules:
                    schedule.is_enabled = False
            else:
                session.delete(app)

        if not soft:
            for path in (
                self._get_app_dir(app_name),
                self.settings.logs_dir / app_name,
                self.settings.backups_dir / app_name,
            ):
                if path.exists():
                    shutil.rmtree(path, ignore_errors=True)
            try:
                self.venv_manager.remove(app_name)
            except RuntimeError as e:
                logger.warning(f"Couldn't fully remove environment for {app_name}: {e}")

        with _git_status_lock:
            _git_status.pop(app_id, None)
        logger.info(f"Deleted app {app_name}")
