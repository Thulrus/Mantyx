"""
FastAPI routes for full-instance backup and restore.
"""

import shutil
import threading
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from mantyx.api.schemas import TaskStartResponse
from mantyx.config import get_settings
from mantyx.core.backup_manager import BackupManager
from mantyx.core.tasks import TaskStatus, task_manager
from mantyx.logging import get_logger

logger = get_logger("api.backup")

router = APIRouter(prefix="/backup", tags=["backup"])


def get_backup_manager() -> BackupManager:
    """Dependency to get a backup manager instance."""
    return BackupManager()


def _run_task_in_background(task_id: str, work: Callable[[], None]) -> None:
    """Run `work` on a daemon thread, marking the task failed on unhandled errors."""

    def _runner():
        try:
            work()
        except Exception as e:
            logger.error(f"Backup task {task_id} failed: {e}")
            task_manager.fail(task_id, str(e))

    threading.Thread(target=_runner, daemon=True).start()


@router.post("/export", response_model=TaskStartResponse)
def export_backup(backup_manager: BackupManager = Depends(get_backup_manager)):
    """Create a full backup archive. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress, then GET /backup/export/{task_id}/download."""
    task = task_manager.create("Creating backup")
    on_log = task_manager.logger_for(task.id)

    def work():
        zip_path = backup_manager.create_backup(on_log=on_log)
        task_manager.complete(task.id, {"zip_path": str(zip_path)})

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Backup started")


@router.get("/export/{task_id}/download")
def download_backup(task_id: str):
    """Download a completed backup archive and delete the server-side temp file."""
    task = task_manager.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.SUCCESS or not task.result:
        raise HTTPException(status_code=400, detail="Backup is not ready")

    zip_path = task.result.get("zip_path")
    if not zip_path:
        raise HTTPException(status_code=400, detail="Backup archive not found")

    path = Path(zip_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Backup archive no longer available")

    return FileResponse(
        path,
        filename=path.name,
        media_type="application/zip",
        background=BackgroundTask(lambda: path.unlink(missing_ok=True)),
    )


@router.post("/import", response_model=TaskStartResponse)
async def import_backup(
    file: UploadFile = File(...),
    backup_manager: BackupManager = Depends(get_backup_manager),
):
    """Restore a full backup archive. This is destructive: it stops the
    scheduler and all running apps, then replaces the current database and
    app files with the archive's contents. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress."""
    settings = get_settings()

    filename = file.filename or "restore.zip"
    temp_path = settings.temp_dir / f"import-{filename}"
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task = task_manager.create("Restoring backup")
    on_log = task_manager.logger_for(task.id)

    def work():
        try:
            result = backup_manager.restore_backup(temp_path, on_log=on_log)
            task_manager.complete(task.id, result)
        finally:
            temp_path.unlink(missing_ok=True)

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Restore started")
