"""
Housekeeping so a long-lived Mantyx instance doesn't fill its disk.

- Log rotation for long-running apps (their stdout/stderr file would
  otherwise grow forever).
- Retention: old run records and their log files, old activity entries,
  per-app update backups beyond the configured count, and stale temp files.

Everything here is conservative: only files inside Mantyx's own logs/backups/
temp directories are touched, the most recent runs of every app are always
kept regardless of age, and running executions are never pruned.
"""

import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import true

from mantyx.config import get_settings
from mantyx.database import get_db
from mantyx.logging import get_logger
from mantyx.models.app import App
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.log import LogEntry

logger = get_logger("maintenance")

# Rotate a running app's log once it passes this size; one previous file is kept.
MAX_LOG_BYTES = 20 * 1024 * 1024
# Always keep at least this many of each app's most recent runs, however old.
KEEP_RECENT_RUNS_PER_APP = 25
# Temp files (unclaimed backup exports, abandoned uploads) older than this are removed.
TEMP_FILE_MAX_AGE_SECONDS = 24 * 3600

O_APPEND = getattr(os, "O_APPEND", 0o2000)


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _fd_is_append_only(pid: int, path: Path) -> bool:
    """True if `pid` has `path` open with O_APPEND (so truncating it is safe).

    Truncating a file that a process writes without O_APPEND would leave its
    write offset past the new end, producing a huge sparse file of zeros.
    Apps started by older Mantyx versions opened their logs that way, so we
    check instead of assuming.
    """
    fd_dir = Path(f"/proc/{pid}/fd")
    try:
        target = str(path.resolve())
        found = False
        for fd in fd_dir.iterdir():
            try:
                if os.readlink(fd) != target:
                    continue
            except OSError:
                continue
            found = True
            flags_line = next(
                (
                    line
                    for line in Path(f"/proc/{pid}/fdinfo/{fd.name}").read_text().splitlines()
                    if line.startswith("flags:")
                ),
                None,
            )
            if flags_line is None or not int(flags_line.split()[1], 8) & O_APPEND:
                return False
        return found
    except OSError:
        return False


def rotate_running_logs() -> None:
    """Rotate oversized stdout/stderr files of running perpetual apps."""
    settings = get_settings()
    with get_db() as session:
        running = (
            session.query(Execution.pid, Execution.stdout_path, Execution.stderr_path)
            .filter(Execution.status == ExecutionStatus.RUNNING, Execution.pid.isnot(None))
            .all()
        )

    for pid, *paths in running:
        for raw in paths:
            if not raw:
                continue
            path = Path(raw)
            try:
                if path.stat().st_size < MAX_LOG_BYTES:
                    continue
            except OSError:
                continue
            if not _is_within(path, settings.logs_dir) or not _fd_is_append_only(pid, path):
                continue
            try:
                shutil.copyfile(path, path.with_name(path.name + ".1"))
                with open(path, "r+") as f:
                    f.truncate(0)
                logger.info(f"Rotated log {path.name}")
            except OSError as e:
                logger.warning(f"Failed to rotate log {path}: {e}")


def _delete_log_file(raw: str | None, logs_dir: Path) -> None:
    if not raw:
        return
    path = Path(raw)
    if not _is_within(path, logs_dir):
        return
    for candidate in (path, path.with_name(path.name + ".1")):
        try:
            candidate.unlink(missing_ok=True)
        except OSError:
            pass


def prune_backups(backups_root: Path, keep: int) -> None:
    """Keep only the newest `keep` update backups inside one app's backup folder."""
    if keep < 1 or not backups_root.is_dir():
        return
    backups = sorted(
        (p for p in backups_root.iterdir() if p.is_dir() and not p.name.startswith("orphaned")),
        key=lambda p: p.name,
        reverse=True,
    )
    for old in backups[keep:]:
        shutil.rmtree(old, ignore_errors=True)


def run_retention() -> None:
    """Apply retention settings. Safe to run at any time."""
    settings = get_settings()
    days = max(1, settings.log_retention_days)
    cutoff = datetime.now() - timedelta(days=days)
    deleted_runs = 0

    try:
        with get_db() as session:
            session.query(LogEntry).filter(LogEntry.timestamp < cutoff).delete(
                synchronize_session=False
            )

        with get_db() as session:
            app_ids = [row[0] for row in session.query(App.id).all()]

        for app_id in app_ids:
            with get_db() as session:
                keep_ids = [
                    row[0]
                    for row in session.query(Execution.id)
                    .filter(Execution.app_id == app_id)
                    .order_by(Execution.id.desc())
                    .limit(KEEP_RECENT_RUNS_PER_APP)
                    .all()
                ]
                old = (
                    session.query(Execution)
                    .filter(
                        Execution.app_id == app_id,
                        Execution.status.notin_([ExecutionStatus.RUNNING, ExecutionStatus.PENDING]),
                        Execution.id.notin_(keep_ids) if keep_ids else true(),
                        Execution.started_at < cutoff,
                    )
                    .all()
                )
                for execution in old:
                    _delete_log_file(execution.stdout_path, settings.logs_dir)
                    _delete_log_file(execution.stderr_path, settings.logs_dir)
                    session.delete(execution)
                    deleted_runs += 1
    except Exception as e:
        logger.warning(f"Run/log retention failed: {e}")

    try:
        if settings.backups_dir.is_dir():
            for app_backups in settings.backups_dir.iterdir():
                if app_backups.is_dir():
                    prune_backups(app_backups, settings.backup_retention_count)
    except OSError as e:
        logger.warning(f"Backup retention failed: {e}")

    try:
        now = time.time()
        if settings.temp_dir.is_dir():
            for entry in settings.temp_dir.iterdir():
                if not (
                    entry.name.startswith("mantyx-backup-") or entry.name.startswith("upload-")
                ):
                    continue
                if now - entry.stat().st_mtime > TEMP_FILE_MAX_AGE_SECONDS:
                    if entry.is_dir():
                        shutil.rmtree(entry, ignore_errors=True)
                    else:
                        entry.unlink(missing_ok=True)
    except OSError as e:
        logger.warning(f"Temp cleanup failed: {e}")

    if deleted_runs:
        logger.info(f"Retention: removed {deleted_runs} run records older than {days} days")
