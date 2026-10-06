"""
FastAPI routes for app management.
"""

import json
import threading
import uuid
from collections.abc import Callable
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from mantyx.api.schemas import (
    AppResponse,
    AppStatusResponse,
    AppUpdate,
    GitUpdateCheckResponse,
    LogEntryResponse,
    TaskResponse,
    TaskStartResponse,
)
from mantyx.config import get_settings
from mantyx.core import runtime
from mantyx.core.app_manager import AppManager, get_git_status, validate_app_name
from mantyx.core.status import build_app_views
from mantyx.core.tasks import StepStatus, TaskConflictError, run_task_in_background, task_manager
from mantyx.database import get_db, get_db_session
from mantyx.logging import get_logger
from mantyx.models.app import App, AppState, AppType
from mantyx.models.log import LogEntry

logger = get_logger("api.apps")

router = APIRouter(prefix="/apps", tags=["apps"])


def get_app_manager() -> AppManager:
    """Dependency: an AppManager wired to the server's shared scheduler/supervisor."""
    return runtime.get_app_manager()


def _run_task_in_background(task_id: str, work: Callable[[], None]) -> None:
    """Run `work` on a daemon thread, marking the task failed on unhandled errors."""
    run_task_in_background(task_id, work)


def _create_task(name: str, app_id: int | None = None, steps=None):
    try:
        return task_manager.create(name, app_id=app_id, steps=steps)
    except TaskConflictError as e:
        raise HTTPException(status_code=409, detail=str(e))


def _get_app_or_404(db: Session, app_id: int) -> App:
    app = db.query(App).filter(App.id == app_id).first()
    if not app or app.is_deleted:
        raise HTTPException(status_code=404, detail="App not found")
    return app


def _app_view(db: Session, app: App) -> dict:
    data = AppResponse.model_validate(app).model_dump()
    data.update(build_app_views(db, [app])[0])
    return data


async def _save_upload(file: UploadFile, prefix: str) -> Path:
    """Stream an upload to a uniquely named temp file, enforcing the size limit."""
    settings = get_settings()
    settings.temp_dir.mkdir(parents=True, exist_ok=True)
    # Never use the client-supplied filename as a path.
    temp_path = settings.temp_dir / f"{prefix}-{uuid.uuid4().hex}.zip"
    limit = settings.max_upload_size_bytes
    written = 0
    try:
        with temp_path.open("wb") as buffer:
            while chunk := await file.read(1024 * 1024):
                written += len(chunk)
                if written > limit:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File is larger than the {settings.max_upload_size_mb} MB limit",
                    )
                buffer.write(chunk)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return temp_path


def _raise_http(e: Exception) -> None:
    if isinstance(e, HTTPException):
        raise e
    if isinstance(e, ValueError):
        raise HTTPException(status_code=400, detail=str(e))
    raise HTTPException(status_code=500, detail=str(e))


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
    """List apps with their user-facing status."""
    query = db.query(App)
    if not include_deleted:
        query = query.filter(App.is_deleted.is_not(True))
    apps = query.order_by(App.display_name).all()
    views = build_app_views(db, apps)
    result = []
    for app, view in zip(apps, views, strict=True):
        data = AppResponse.model_validate(app).model_dump()
        data.update(view)
        result.append(data)
    return result


@router.get("/{app_id}", response_model=AppResponse)
def get_app(app_id: int, db: Session = Depends(get_db_session)):
    """Get a specific app with its user-facing status."""
    return _app_view(db, _get_app_or_404(db, app_id))


def _parse_schedule(schedule: str | None) -> dict | None:
    if not schedule:
        return None
    try:
        data = json.loads(schedule)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid schedule")
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="Invalid schedule")
    if data.get("schedule_type"):
        from mantyx.core.scheduler import build_trigger, get_effective_timezone

        try:
            build_trigger(
                data.get("schedule_type"),
                data.get("cron_expression"),
                data.get("interval_seconds"),
                get_effective_timezone(),
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    return data


def _check_new_app(app_name: str, app_type: str, db: Session) -> AppType:
    try:
        validate_app_name(app_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    try:
        app_type_enum = AppType[app_type.upper()]
    except KeyError:
        raise HTTPException(status_code=400, detail=f"Invalid app_type: {app_type}")
    existing = db.query(App).filter(App.name == app_name, App.is_deleted.is_not(True)).first()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"An app with the ID '{app_name}' already exists"
        )
    return app_type_enum


def _setup_steps(source_label: str, app_type: AppType, install: bool, activate: bool):
    steps = [("source", source_label)]
    if install:
        steps.append(("install", "Install dependencies"))
        if app_type == AppType.SCHEDULED:
            steps.append(("schedule", "Add schedule"))
        if activate:
            steps.append(
                ("activate", "Start app" if app_type == AppType.PERPETUAL else "Activate schedule")
            )
    return steps


def _new_app_work(
    task, create: Callable[[], dict], *, install, activate, schedule, manager, cleanup=None
):
    on_log = task_manager.logger_for(task.id)

    def on_step(key, status):
        task_manager.step(task.id, key, status)

    def work():
        try:
            on_step("source", StepStatus.RUNNING)
            result = create()
            task_manager.set_app(task.id, result["id"])
            on_step("source", StepStatus.DONE)
        finally:
            if cleanup:
                cleanup()
        if install:
            manager.provision_app(
                result["id"],
                schedule=schedule,
                activate=activate,
                on_log=on_log,
                on_step=on_step,
            )
        task_manager.complete(task.id, {"app_id": result["id"], "app_name": result["name"]})

    return work


@router.post("/upload/zip", response_model=TaskStartResponse)
async def upload_zip(
    file: UploadFile = File(...),
    app_name: str = Form(...),
    display_name: str = Form(...),
    app_type: str = Form("PERPETUAL"),
    description: str | None = Form(None),
    install: bool = Form(False),
    activate: bool = Form(False),
    schedule: str | None = Form(None),
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Add an app from a ZIP file. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress.

    With install=true the dependencies are installed too; with activate=true
    the app is then started (always-running) or its schedule turned on.
    `schedule` is an optional JSON schedule definition for scheduled apps.
    """
    app_name = app_name.strip()
    app_type_enum = _check_new_app(app_name, app_type, db)
    schedule_data = _parse_schedule(schedule)

    temp_path = await _save_upload(file, "upload")
    task = _create_task(
        f"Adding {display_name}",
        steps=_setup_steps("Upload files", app_type_enum, install, activate),
    )

    work = _new_app_work(
        task,
        lambda: app_manager.create_app_from_zip(
            temp_path,
            app_name,
            display_name.strip() or app_name,
            description,
            app_type_enum,
            on_log=task_manager.logger_for(task.id),
        ),
        install=install,
        activate=activate,
        schedule=schedule_data,
        manager=app_manager,
        cleanup=lambda: temp_path.unlink(missing_ok=True),
    )
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
    install: bool = Form(False),
    activate: bool = Form(False),
    schedule: str | None = Form(None),
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Add an app from a Git repository. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress."""
    app_name = app_name.strip()
    app_type_enum = _check_new_app(app_name, app_type, db)
    schedule_data = _parse_schedule(schedule)

    task = _create_task(
        f"Adding {display_name}",
        steps=_setup_steps("Clone repository", app_type_enum, install, activate),
    )
    work = _new_app_work(
        task,
        lambda: app_manager.create_app_from_git(
            git_url.strip(),
            app_name,
            display_name.strip() or app_name,
            branch.strip() or "main",
            description,
            app_type_enum,
            on_log=task_manager.logger_for(task.id),
        ),
        install=install,
        activate=activate,
        schedule=schedule_data,
        manager=app_manager,
    )
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
    app = _get_app_or_404(db, app_id)
    if app.state != AppState.UPLOADED:
        raise HTTPException(status_code=400, detail=f"{app.display_name} is already installed")

    task = _create_task(f"Installing {app.display_name}", app_id=app_id)
    on_log = task_manager.logger_for(task.id)

    def work():
        app_manager.install_app(app_id, on_log=on_log)
        task_manager.complete(task.id, {"app_id": app_id})

    _run_task_in_background(task.id, work)
    return TaskStartResponse(task_id=task.id, message="Install started")


def _sync_action(app_id: int, action: Callable[[int], None], db: Session) -> dict:
    _get_app_or_404(db, app_id)
    if task_manager.active_for_app(app_id):
        raise HTTPException(status_code=409, detail="Another operation is in progress for this app")
    try:
        action(app_id)
    except Exception as e:
        _raise_http(e)
    db.expire_all()
    return _app_view(db, _get_app_or_404(db, app_id))


@router.post("/{app_id}/enable", response_model=AppResponse)
def enable_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Activate an app (scheduled apps resume their schedules; always-running apps start)."""
    return _sync_action(app_id, app_manager.enable_app, db)


@router.post("/{app_id}/disable", response_model=AppResponse)
def disable_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Pause an app (stops it if running; schedules stop firing)."""
    return _sync_action(app_id, app_manager.disable_app, db)


@router.post("/{app_id}/start", response_model=AppResponse)
def start_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Start an always-running app."""
    return _sync_action(app_id, app_manager.start_app, db)


@router.post("/{app_id}/stop", response_model=AppResponse)
def stop_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Stop a running app. It stays stopped (also across Mantyx restarts) until started."""
    return _sync_action(app_id, app_manager.stop_app, db)


@router.post("/{app_id}/restart", response_model=AppResponse)
def restart_app(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Restart an always-running app (starts it if it isn't running)."""
    return _sync_action(app_id, app_manager.restart_app, db)


@router.post("/{app_id}/update/zip", response_model=TaskStartResponse)
async def update_app_zip(
    app_id: int,
    file: UploadFile = File(...),
    backup: bool = Form(True),
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Update an app from a ZIP file. Runs in the background; poll
    GET /apps/tasks/{task_id} for progress."""
    app = _get_app_or_404(db, app_id)
    temp_path = await _save_upload(file, "upload")
    try:
        task = _create_task(f"Updating {app.display_name}", app_id=app_id)
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    on_log = task_manager.logger_for(task.id)

    def work():
        try:
            result = app_manager.update_app_from_zip(
                app_id, temp_path, backup=backup, on_log=on_log
            )
            task_manager.complete(task.id, result)
        finally:
            temp_path.unlink(missing_ok=True)

    _run_task_in_background(task.id, work)
    return TaskStartResponse(task_id=task.id, message="Update started")


@router.post("/{app_id}/update/git", response_model=TaskStartResponse)
def update_app_git(
    app_id: int,
    backup: bool = Form(True),
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Pull latest changes from Git repository for an app. Runs in the
    background; poll GET /apps/tasks/{task_id} for progress."""
    app = _get_app_or_404(db, app_id)
    if not app.git_url:
        raise HTTPException(status_code=400, detail="This app wasn't added from Git")
    task = _create_task(f"Updating {app.display_name}", app_id=app_id)
    on_log = task_manager.logger_for(task.id)

    def work():
        result = app_manager.pull_git_app(app_id, backup=backup, on_log=on_log)
        task_manager.complete(task.id, result)

    _run_task_in_background(task.id, work)
    return TaskStartResponse(task_id=task.id, message="Update started")


@router.post("/{app_id}/rebuild-venv", response_model=TaskStartResponse)
def rebuild_app_venv(
    app_id: int,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Delete and recreate an app's virtual environment, then reinstall its
    requirements. Runs in the background; poll GET /apps/tasks/{task_id} for progress."""
    app = _get_app_or_404(db, app_id)
    task = _create_task(f"Rebuilding environment for {app.display_name}", app_id=app_id)
    on_log = task_manager.logger_for(task.id)

    def work():
        result = app_manager.rebuild_app_venv(app_id, on_log=on_log)
        task_manager.complete(task.id, result)

    _run_task_in_background(task.id, work)
    return TaskStartResponse(task_id=task.id, message="Rebuild started")


@router.get("/{app_id}/check-git-update", response_model=GitUpdateCheckResponse)
async def check_git_update(
    app_id: int,
    refresh: bool = False,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Whether the remote Git repository has new commits.

    Returns the cached result from the periodic background check unless
    refresh=true (which fetches from the remote now).
    """
    cached = get_git_status(app_id)
    if cached and not refresh and cached.get("update_available") is not None:
        with get_db() as db:
            name = _get_app_or_404(db, app_id).name
        return GitUpdateCheckResponse(
            app_id=app_id,
            app_name=name,
            update_available=bool(cached.get("update_available")),
            commits_behind=cached.get("commits_behind") or 0,
            local_commit=cached.get("local_commit") or "",
            remote_commit=cached.get("remote_commit") or "",
        )
    try:
        result = await run_in_threadpool(app_manager.check_git_update, app_id)
        return GitUpdateCheckResponse(**result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Couldn't reach the Git remote: {e}")


@router.get("/{app_id}/backups")
def list_app_backups(app_id: int, app_manager: AppManager = Depends(get_app_manager)):
    """Saved previous versions of an app, newest first."""
    try:
        return app_manager.list_backups(app_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{app_id}/backups/{backup_id}/restore", response_model=TaskStartResponse)
def restore_app_backup(
    app_id: int,
    backup_id: str,
    app_manager: AppManager = Depends(get_app_manager),
    db: Session = Depends(get_db_session),
):
    """Roll an app back to a saved version. Runs in the background."""
    app = _get_app_or_404(db, app_id)
    task = _create_task(f"Rolling back {app.display_name}", app_id=app_id)
    on_log = task_manager.logger_for(task.id)

    def work():
        result = app_manager.restore_app_backup(app_id, backup_id, on_log=on_log)
        task_manager.complete(task.id, result)

    _run_task_in_background(task.id, work)
    return TaskStartResponse(task_id=task.id, message="Rollback started")


@router.get("/{app_id}/files")
def list_app_files(app_id: int, app_manager: AppManager = Depends(get_app_manager)):
    """Python files in the app that could be its entrypoint."""
    try:
        return {"python_files": app_manager.list_python_files(app_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/{app_id}/events", response_model=list[LogEntryResponse])
def list_app_events(app_id: int, limit: int = 50, db: Session = Depends(get_db_session)):
    """Recent activity for an app (starts, crashes, updates, ...), newest first."""
    _get_app_or_404(db, app_id)
    return (
        db.query(LogEntry)
        .filter(LogEntry.app_id == app_id)
        .order_by(LogEntry.id.desc())
        .limit(min(max(limit, 1), 200))
        .all()
    )


@router.post("/{app_id}/run")
def run_scheduled_app(
    app_id: int,
    db: Session = Depends(get_db_session),
):
    """Run a scheduled app immediately."""
    from mantyx.core.scheduler import (
        MANUAL_RUN_STATES,
        execute_scheduled_app,
        is_app_run_in_progress,
    )

    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    if app.app_type != AppType.SCHEDULED:
        raise HTTPException(status_code=400, detail="App is not a scheduled app")

    if app.state == AppState.UPLOADED:
        raise HTTPException(status_code=400, detail="Install the app before running it")
    if app.state not in MANUAL_RUN_STATES:
        raise HTTPException(status_code=400, detail=f"Cannot run app in state: {app.state.value}")
    if is_app_run_in_progress(app_id):
        raise HTTPException(status_code=409, detail=f"{app.display_name} is already running")

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
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

    return {"message": "App execution started"}


@router.delete("/{app_id}")
def delete_app(
    app_id: int,
    soft: bool = False,
    app_manager: AppManager = Depends(get_app_manager),
):
    """Delete an app and everything that belongs to it (files, data, logs, history)."""
    if task_manager.active_for_app(app_id):
        raise HTTPException(
            status_code=409, detail="Wait for the current operation on this app to finish"
        )
    try:
        app_manager.delete_app(app_id, soft=soft)
        return {"message": "App deleted"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/{app_id}", response_model=AppResponse)
def update_app_config(
    app_id: int,
    app_update: AppUpdate,
    db: Session = Depends(get_db_session),
    app_manager: AppManager = Depends(get_app_manager),
):
    """Update an app's configuration."""
    app = _get_app_or_404(db, app_id)

    fields = app_update.model_dump(exclude_unset=True)

    if "app_type" in fields and fields["app_type"] != app.app_type:
        if app.state == AppState.RUNNING:
            raise HTTPException(status_code=400, detail="Stop the app before changing its type")
    if fields.get("entrypoint"):
        try:
            fields["entrypoint"] = app_manager.validate_entrypoint(app_id, fields["entrypoint"])
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
    elif "entrypoint" in fields:
        del fields["entrypoint"]
    if "web_url" in fields and fields["web_url"] is not None:
        fields["web_url"] = fields["web_url"].strip() or None
        if fields["web_url"] and not fields["web_url"].startswith(("http://", "https://")):
            raise HTTPException(status_code=400, detail="Link must start with http:// or https://")

    for field, value in fields.items():
        setattr(app, field, value)

    # A user explicitly touching the web link takes it out of auto-detection:
    # if they cleared both fields, hand control back to the port monitor;
    # otherwise mark it manual so the background detector leaves it alone.
    if "web_url" in fields or "web_port" in fields:
        app.web_port_source = "manual" if (app.web_url or app.web_port) else None

    db.commit()
    db.refresh(app)
    return _app_view(db, app)


@router.post("/{app_id}/detect-port", response_model=AppResponse)
def detect_app_port(
    app_id: int,
    db: Session = Depends(get_db_session),
):
    """Retry automatic web-port detection now instead of waiting for the next monitor tick.

    No-ops (but still returns the current app) if the app isn't running or the
    web link has been set manually — clear it first via PATCH to re-enable detection.
    """
    app = _get_app_or_404(db, app_id)

    if app.web_port_source != "manual" and app.pid:
        runtime.get_supervisor()._maybe_detect_web_port(app.id, app.pid)
        db.refresh(app)

    return _app_view(db, app)


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
