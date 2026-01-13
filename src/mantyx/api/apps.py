"""
FastAPI routes for app management.
"""

import shutil
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from mantyx.api.schemas import AppCreate, AppResponse, AppStatusResponse, AppUpdate, UploadResponse
from mantyx.config import get_settings
from mantyx.core.app_manager import AppManager
from mantyx.database import get_db_session
from mantyx.models.app import App, AppType

router = APIRouter(prefix="/apps", tags=["apps"])


def get_app_manager() -> AppManager:
    """Dependency to get app manager instance."""
    return AppManager()


@router.get("", response_model=list[AppResponse])
def list_apps(
        include_deleted: bool = False,
        db: Session = Depends(get_db_session),
):
    """List all apps."""
    query = db.query(App)
    if not include_deleted:
        query = query.filter(App.is_deleted == False)
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


@router.post("/upload/zip", response_model=UploadResponse)
async def upload_zip(
        file: UploadFile = File(...),
        app_name: str = Form(...),
        display_name: str = Form(...),
        app_type: str = Form("PERPETUAL"),
        description: Optional[str] = Form(None),
        app_manager: AppManager = Depends(get_app_manager),
):
    """Upload and create an app from a ZIP file."""
    settings = get_settings()

    # Save uploaded file
    temp_path = settings.temp_dir / file.filename
    temp_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with temp_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)

        # Convert string to AppType enum
        try:
            app_type_enum = AppType[app_type.upper()]
        except KeyError:
            raise HTTPException(status_code=400,
                                detail=f"Invalid app_type: {app_type}")

        # Create app
        app = app_manager.create_app_from_zip(
            temp_path,
            app_name,
            display_name,
            description,
            app_type_enum,
        )

        # Handle dict return (id and name)
        if isinstance(app, dict):
            return UploadResponse(
                app_id=app["id"],
                app_name=app["name"],
                message="App uploaded successfully",
            )

        # Fallback for App object (shouldn't happen with new code)
        return UploadResponse(
            app_id=app.id,
            app_name=app.name,
            message="App uploaded successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Failed to upload app: {str(e)}")
    finally:
        if temp_path.exists():
            temp_path.unlink()


@router.post("/upload/git", response_model=UploadResponse)
async def upload_git(
        git_url: str = Form(...),
        app_name: str = Form(...),
        display_name: str = Form(...),
        branch: str = Form("main"),
        app_type: str = Form("PERPETUAL"),
        description: Optional[str] = Form(None),
        app_manager: AppManager = Depends(get_app_manager),
):
    """Create an app from a Git repository."""
    try:
        # Convert string to AppType enum
        try:
            app_type_enum = AppType[app_type.upper()]
        except KeyError:
            raise HTTPException(status_code=400,
                                detail=f"Invalid app_type: {app_type}")

        app = app_manager.create_app_from_git(
            git_url,
            app_name,
            display_name,
            branch,
            description,
            app_type_enum,
        )

        # Handle dict return (id and name)
        if isinstance(app, dict):
            return UploadResponse(
                app_id=app["id"],
                app_name=app["name"],
                message="App created from Git successfully",
            )

        # Fallback for App object (shouldn't happen with new code)
        return UploadResponse(
            app_id=app.id,
            app_name=app.name,
            message="App created from Git successfully",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500,
                            detail=f"Failed to create app from Git: {str(e)}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
        raise HTTPException(status_code=400,
                            detail="Only perpetual apps can be started")

    try:
        app_manager.supervisor.start_app(app)
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
        app_manager.supervisor.restart_app(app)
        return {"message": "App restarted successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    for field, value in app_update.model_dump(exclude_unset=True).items():
        setattr(app, field, value)

    db.commit()
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
