"""
FastAPI routes for schedules.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from mantyx.api.schemas import ScheduleCreate, ScheduleResponse, ScheduleUpdate
from mantyx.core.scheduler import AppScheduler
from mantyx.database import get_db_session
from mantyx.models.schedule import Schedule

router = APIRouter(prefix="/schedules", tags=["schedules"])


def get_scheduler() -> AppScheduler:
    """Dependency to get scheduler instance."""
    from mantyx.app import scheduler
    if scheduler is None:
        raise HTTPException(status_code=500,
                            detail="Scheduler not initialized")
    return scheduler


@router.get("", response_model=list[ScheduleResponse])
def list_schedules(
        app_id: int | None = None,
        db: Session = Depends(get_db_session),
):
    """List all schedules."""
    query = db.query(Schedule)
    if app_id:
        query = query.filter(Schedule.app_id == app_id)
    schedules = query.all()
    return schedules


@router.get("/{schedule_id}", response_model=ScheduleResponse)
def get_schedule(
        schedule_id: int,
        db: Session = Depends(get_db_session),
):
    """Get a specific schedule."""
    schedule = db.query(Schedule).filter(Schedule.id == schedule_id).first()
    if not schedule:
        raise HTTPException(status_code=404, detail="Schedule not found")
    return schedule


@router.post("", response_model=ScheduleResponse)
def create_schedule(
        schedule_create: ScheduleCreate,
        db: Session = Depends(get_db_session),
        scheduler: AppScheduler = Depends(get_scheduler),
):
    """Create a new schedule."""
    schedule = Schedule(**schedule_create.model_dump())
    db.add(schedule)
    db.commit()
    db.refresh(schedule)

    # Add to scheduler if enabled
    if schedule.is_enabled:
        try:
            scheduler.add_schedule(schedule)
        except Exception as e:
            # Rollback if scheduler fails
            db.delete(schedule)
            db.commit()
            raise HTTPException(status_code=500,
                                detail=f"Failed to add schedule: {e}")

    return schedule


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

    # Update fields
    for field, value in schedule_update.model_dump(exclude_unset=True).items():
        setattr(schedule, field, value)

    db.commit()
    db.refresh(schedule)

    # Update scheduler
    if schedule.is_enabled:
        scheduler.add_schedule(schedule)
    else:
        scheduler.remove_schedule(schedule_id)

    return schedule


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

    # Remove from scheduler
    scheduler.remove_schedule(schedule_id)

    db.delete(schedule)
    db.commit()

    return {"message": "Schedule deleted successfully"}


@router.post("/{schedule_id}/enable")
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

    scheduler.add_schedule(schedule)

    return {"message": "Schedule enabled successfully"}


@router.post("/{schedule_id}/disable")
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

    return {"message": "Schedule disabled successfully"}


@router.get("/debug/scheduler-status")
def get_scheduler_status(scheduler: AppScheduler = Depends(get_scheduler), ):
    """Get detailed scheduler status for debugging."""
    return scheduler.get_scheduler_status()
