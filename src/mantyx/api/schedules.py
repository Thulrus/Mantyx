"""
FastAPI routes for schedules.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mantyx.api.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from mantyx.core import runtime
from mantyx.core.scheduler import (
    AppScheduler,
    build_trigger,
    get_effective_timezone,
    preview_fire_times,
)
from mantyx.database import get_db_session
from mantyx.models.app import App, AppType
from mantyx.models.schedule import Schedule

router = APIRouter(prefix="/schedules", tags=["schedules"])


def get_scheduler() -> AppScheduler:
    """Dependency to get the server's scheduler instance."""
    scheduler = runtime.get_scheduler()
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler not initialized")
    return scheduler


class SchedulePreviewRequest(BaseModel):
    schedule_type: str
    cron_expression: str | None = None
    interval_seconds: int | None = None
    count: int = 3


def _validate(schedule_type, cron_expression, interval_seconds):
    try:
        return build_trigger(
            schedule_type, cron_expression, interval_seconds, get_effective_timezone()
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


def _response(schedule: Schedule, scheduler: AppScheduler | None) -> dict:
    data = ScheduleResponse.model_validate(schedule).model_dump()
    data["next_run"] = scheduler.next_run_time(schedule.id) if scheduler else None
    return data


def _sync_job(schedule: Schedule, scheduler: AppScheduler) -> None:
    if schedule.is_enabled and not schedule.app.is_deleted:
        scheduler.add_schedule(schedule)
    else:
        scheduler.remove_schedule(schedule.id)


@router.post("/preview")
def preview_schedule(request: SchedulePreviewRequest):
    """Validate a schedule definition and return its next few run times."""
    trigger = _validate(request.schedule_type, request.cron_expression, request.interval_seconds)
    times = preview_fire_times(trigger, max(1, min(request.count, 10)))
    return {
        "timezone": get_effective_timezone(),
        "next_runs": [t.isoformat() for t in times],
    }


@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
    app_id: int | None = None,
    db: Session = Depends(get_db_session),
):
    """List all schedules."""
    query = db.query(Schedule)
    if app_id:
        query = query.filter(Schedule.app_id == app_id)
    scheduler = runtime.get_scheduler()
    return [_response(s, scheduler) for s in query.order_by(Schedule.id).all()]


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
    schedule_id: int,
    db: Session = Depends(get_db_session),
):
    """Get a specific schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return _response(schedule, runtime.get_scheduler())


@router.post("", response_model=ScheduleResponse)
def create_schedule(
    schedule_create: ScheduleCreate,
    db: Session = Depends(get_db_session),
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Create a new schedule."""
    app = db.query(App).filter(App.id == schedule_create.app_id).first()
    if not app or app.is_deleted:
        raise HTTPException(status_code=404, detail="App not found")
    if app.app_type != AppType.SCHEDULED:
        raise HTTPException(status_code=400, detail="Schedules can only be added to scheduled apps")

    data = schedule_create.model_dump()
    _validate(data["schedule_type"], data.get("cron_expression"), data.get("interval_seconds"))
    is_enabled = data.pop("is_enabled", True)
    if data["schedule_type"] == "cron":
        data["interval_seconds"] = None
    else:
        data["cron_expression"] = None
    data["timezone"] = get_effective_timezone()

    schedule = Schedule(**data, is_enabled=is_enabled)
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    _sync_job(schedule, scheduler)
    return _response(schedule, scheduler)


@router.patch("/{schedule_id}", response_model=ScheduleResponse)
def update_schedule(
    schedule_id: int,
    schedule_update: ScheduleUpdate,
    db: Session = Depends(get_db_session),
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Update a schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    fields = schedule_update.model_dump(exclude_unset=True)
    schedule_type = fields.get("schedule_type", schedule.schedule_type)
    cron_expression = fields.get("cron_expression", schedule.cron_expression)
    interval_seconds = fields.get("interval_seconds", schedule.interval_seconds)
    _validate(schedule_type, cron_expression, interval_seconds)

    for field, value in fields.items():
        setattr(schedule, field, value)
    # Keep only the fields that belong to the schedule's type.
    if schedule.schedule_type == "cron":
        schedule.interval_seconds = None
    else:
        schedule.cron_expression = None

    db.commit()
    db.refresh(schedule)
    _sync_job(schedule, scheduler)
    return _response(schedule, scheduler)


@router.delete("/{schedule_id}")
def delete_schedule(
    schedule_id: int,
    db: Session = Depends(get_db_session),
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Delete a schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    scheduler.remove_schedule(schedule_id)
    db.delete(schedule)
    db.commit()

    return {"message": "Schedule deleted"}


@router.post("/{schedule_id}/enable", response_model=ScheduleResponse)
def enable_schedule(
    schedule_id: int,
    db: Session = Depends(get_db_session),
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Enable a schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule.is_enabled = True
    db.commit()
    _sync_job(schedule, scheduler)
    return _response(schedule, scheduler)


@router.post("/{schedule_id}/disable", response_model=ScheduleResponse)
def disable_schedule(
    schedule_id: int,
    db: Session = Depends(get_db_session),
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Disable a schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")

    schedule.is_enabled = False
    db.commit()
    scheduler.remove_schedule(schedule_id)
    return _response(schedule, scheduler)


@router.get("/debug/scheduler-status")
def get_scheduler_status(
    scheduler: AppScheduler = Depends(get_scheduler),
):
    """Get detailed scheduler status for diagnostics."""
    return scheduler.get_scheduler_status()
