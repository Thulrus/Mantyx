"""
FastAPI routes for app management.
"""

import shutil
import threading
from collections.abc import Callable

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from mantyx.api.schemas import (
    AppResponse,
    AppStatusResponse,
    AppUpdate,
    GitUpdateCheckResponse,
    TaskResponse,
    TaskStartResponse,
)
from mantyx.config import get_settings
from mantyx.core.app_manager import AppManager
from mantyx.core.tasks import task_manager
from mantyx.database import get_db_session
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState, AppType

logger = get_logger("api.apps")

router = APIRouter(prefix="/apps", tags=["apps"])


def get_app_manager() -> AppManager:
    """Dependency to get app manager instance."""
    return AppManager()


def _run_task_in_background(task_id: str, work: Callable[[], None]) -> None:
    """Run `work` on a daemon thread, marking the task failed on unhandled errors."""

    def _runner():
        try:
            work()
        except Exception as e:
            task_manager.fail(task_id, str(e))

    threading.Thread(target=_runner, daemon=True).start()


@router.get("/tasks/{task_id}", response_model=TaskResponse)
def get_task(task_id: str, since: int = 0):
    """Poll progress/logs for a background operation (upload, install, update)."""
    task = task_manager.to_dict(task_id, since=since)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return task


@router.get("", response_model=list[AppResponse])
def list_apps(
    include_deleted: bool = False,
    db: Session = Depends(get_db_session),
):
    """List all apps."""
    query = db.query(App)
    if not include_deleted:
        query = query.filter(App.is_deleted.is_not(True))
    apps = query.all()
    return apps


@router.get("/{app_id}", response_model=AppResponse)
def get_app(
    app_id: int,
    db: Session = Depends(get_db_session),
):
    """Get a specific app."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    return app


@router.post("/upload/zip", response_model=TaskStartResponse)
async def upload_zip(
    file: UploadFile = File(...),
    app_name: str = Form(...),
    display_name: str = Form(...),
    app_type: str = Form("PERPETUAL"),
    description: str | None = Form(None),
    app_manager: AppManager = Depends(get_app_manager),
):
    """Upload and create an app from a ZIP file. Extraction runs in the background;
    poll GET /apps/tasks/{task_id} for progress."""
    settings = get_settings()

    # Convert string to AppType enum up front so bad requests fail fast
    try:
        app_type_enum = AppType[app_type.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid app_type: {app_type}")

    # Save uploaded file (must happen in the request handler; the stream isn't
    # available once we return)
    temp_path = settings.temp_dir / file.filename
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task = task_manager.create(f"Uploading {app_name}")
    on_log = task_manager.logger_for(task.id)

    def work():
        try:
            result = app_manager.create_app_from_zip(
                temp_path,
                app_name,
                display_name,
                description,
                app_type_enum,
                on_log=on_log,
            )
            task_manager.complete(task.id, {"app_id": result["id"], "app_name": result["name"]})
        finally:
            if temp_path.exists():
                temp_path.unlink()

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Upload started")


@router.post("/upload/git", response_model=TaskStartResponse)
async def upload_git(
    git_url: str = Form(...),
    app_name: str = Form(...),
    display_name: str = Form(...),
    branch: str = Form("main"),
    app_type: str = Form("PERPETUAL"),
    description: str | None = Form(None),
    app_manager: AppManager = Depends(get_app_manager),
):
    """Create an app from a Git repository. Clone runs in the background;
    poll GET /apps/tasks/{task_id} for progress."""
    try:
        app_type_enum = AppType[app_type.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid app_type: {app_type}")

    task = task_manager.create(f"Cloning {app_name} from Git")
    on_log = task_manager.logger_for(task.id)

    def work():
        result = app_manager.create_app_from_git(
            git_url,
            app_name,
            display_name,
            branch,
            description,
            app_type_enum,
            on_log=on_log,
        )
        task_manager.complete(task.id, {"app_id": result["id"], "app_name": result["name"]})

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Clone started")


@router.post("/{app_id}/install", response_model=TaskStartResponse)
def install_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Install an app's dependencies. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")
    if app.state != AppState.UPLOADED:
        raise HTTPException(status_code=400, detail=f"App {app.name} is not in uploaded state")

    task = task_manager.create(f"Installing {app.name}")
    on_log = task_manager.logger_for(task.id)

    def work():
        app_manager.install_app(app_id, on_log=on_log)
        task_manager.complete(task.id, {"app_id": app_id})

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Install started")


@router.post("/{app_id}/enable")
def enable_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Enable an app."""
    try:
        app_manager.enable_app(app_id)
        return {"message": "App enabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/disable")
def disable_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Disable an app."""
    try:
        app_manager.disable_app(app_id)
        return {"message": "App disabled successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/start")
def start_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Start a perpetual app."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    if app.app_type != AppType.PERPETUAL:
        raise HTTPException(status_code=400, detail="Only perpetual apps can be started")

    try:
        app_manager.supervisor.start_app(app_id)
        return {"message": "App started successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/stop")
def stop_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Stop a running app."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    try:
        app_manager.supervisor.stop_app(app)
        return {"message": "App stopped successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/restart")
def restart_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Restart an app."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    try:
        app_manager.supervisor.restart_app(app.id)
        return {"message": "App restarted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{app_id}/update/zip", response_model=TaskStartResponse)
async def update_app_zip(
    app_id: int,
    file: UploadFile = File(...),
    backup: bool = Form(True),
    app_manager: AppManager = Depends(get_app_manager),
):
    """Update an app from a ZIP file. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress."""
    settings = get_settings()

    # Save uploaded file
    filename = file.filename or f"update_{app_id}.zip"
    temp_path = settings.temp_dir / filename
    temp_path.parent.mkdir(parents=True, exist_ok=True)
    with temp_path.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    task = task_manager.create(f"Updating app {app_id}")
    on_log = task_manager.logger_for(task.id)

    def work():
        try:
            result = app_manager.update_app_from_zip(
                app_id,
                temp_path,
                backup=backup,
                on_log=on_log,
            )
            task_manager.complete(task.id, result)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Update started")


@router.post("/{app_id}/update/git", response_model=TaskStartResponse)
def update_app_git(
    app_id: int,
    backup: bool = Form(True),
    app_manager: AppManager = Depends(get_app_manager),
):
    """Pull latest changes from Git repository for an app. Runs in the
    background; poll GET /apps/tasks/{task_id} for progress."""
    task = task_manager.create(f"Pulling Git updates for app {app_id}")
    on_log = task_manager.logger_for(task.id)

    def work():
        result = app_manager.pull_git_app(app_id, backup=backup, on_log=on_log)
        task_manager.complete(task.id, result)

    _run_task_in_background(task.id, work)

    return TaskStartResponse(task_id=task.id, message="Update started")


@router.get("/{app_id}/check-git-update", response_model=GitUpdateCheckResponse)
def check_git_update(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Check if the remote Git repository has new commits (read-only, safe to call anytime)."""
    try:
        result = app_manager.check_git_update(app_id)
        return GitUpdateCheckResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check Git updates: {str(e)}")


@router.post("/{app_id}/run")
def run_scheduled_app(
    app_id: int,
    db: Session = Depends(get_db_session),
):
    """Run a scheduled app immediately."""
    import threading

    from mantyx.core.scheduler import execute_scheduled_app

    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    if app.app_type != AppType.SCHEDULED:
        raise HTTPException(status_code=400, detail="App is not a scheduled app")

    if app.state not in (AppState.ENABLED, AppState.STOPPED, AppState.INSTALLED, AppState.DISABLED):
        raise HTTPException(status_code=400, detail=f"Cannot run app in state: {app.state}")

    app_name = app.name

    def _run():
        try:
            execute_scheduled_app(app_id, None)
        except Exception as exc:
            logger.error(
                f"Background execution failed for app {app_name} ({app_id}): {exc}",
                app_id=app_id,
            )

    # Run in background thread to not block API response
    thread = threading.Thread(target=_run)
    thread.start()

    return {"message": "App execution started"}


@router.delete("/{app_id}")
def delete_app(
    app_id: int,
    soft: bool = True,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Delete an app."""
    try:
        app_manager.delete_app(app_id, soft=soft)
        return {"message": "App deleted successfully"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{app_id}", response_model=AppResponse)
def update_app_config(
    app_id: int,
    app_update: AppUpdate,
    db: Session = Depends(get_db_session),
):
    """Update an app's configuration."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    # Update fields
    fields = app_update.model_dump(exclude_unset=True)
    for field, value in fields.items():
        setattr(app, field, value)

    # A user explicitly touching the web link takes it out of auto-detection:
    # if they cleared both fields, hand control back to the port monitor;
    # otherwise mark it manual so the background detector leaves it alone.
    if "web_url" in fields or "web_port" in fields:
        app.web_port_source = "manual" if (app.web_url or app.web_port) else None

    db.commit()
    db.refresh(app)
    return app


@router.post("/{app_id}/detect-port", response_model=AppResponse)
def detect_app_port(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Retry automatic web-port detection now instead of waiting for the next monitor tick.

    No-ops (but still returns the current app) if the app isn't running or the
    web link has been set manually — clear it first via PATCH to re-enable detection.
    """
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    if app.web_port_source != "manual" and app.pid:
        app_manager.supervisor._maybe_detect_web_port(app.id, app.pid)
        db.refresh(app)

    return app


@router.get("/{app_id}/status", response_model=AppStatusResponse)
def get_app_status(
    app_id: int,
    db: Session = Depends(get_db_session),
):
    """Get detailed status of an app."""
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    return AppStatusResponse(
        app_id=app.id,
        app_name=app.name,
        state=app.state,
        is_running=app.is_running,
        can_start=app.can_start,
        can_stop=app.can_stop,
        can_enable=app.can_enable,
        can_disable=app.can_disable,
    )
