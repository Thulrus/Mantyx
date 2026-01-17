"""
FastAPI routes for system settings.
"""

from typing import Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from mantyx.config import get_system_timezone
from mantyx.database import get_db_session
from mantyx.models.setting import Setting

router = APIRouter(prefix="/settings", tags=["settings"])


class SettingUpdate(BaseModel):
    value: str


def get_setting(db: Session,
                key: str,
                default: str | None = None) -> str | None:
    """Get a setting value from the database."""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        return setting.value
    return default


def set_setting(db: Session,
                key: str,
                value: str,
                description: str | None = None) -> None:
    """Set a setting value in the database."""
    setting = db.query(Setting).filter(Setting.key == key).first()
    if setting:
        setting.value = value
        if description:
            setting.description = description
    else:
        setting = Setting(key=key, value=value, description=description)
        db.add(setting)
    db.commit()


@router.get("")
def get_settings(db: Session = Depends(get_db_session)) -> Dict[str, str]:
    """Get all settings."""
    settings = db.query(Setting).all()
    result = {s.key: s.value for s in settings}

    # If timezone not set, use auto-detected one
    if "timezone" not in result:
        result["timezone"] = get_system_timezone()

    return result


@router.get("/timezone")
def get_timezone_setting(db: Session = Depends(get_db_session)) -> Dict[str,
                                                                        str]:
    """Get the configured timezone."""
    tz = get_setting(db, "timezone")
    if not tz:
        tz = get_system_timezone()

    return {
        "timezone": tz,
        "detected_timezone": get_system_timezone(),
    }


@router.put("/timezone")
def update_timezone(
        setting_update: SettingUpdate,
        db: Session = Depends(get_db_session),
) -> Dict[str, str]:
    """Update the timezone setting."""
    from zoneinfo import available_timezones

    # Validate timezone
    tz = setting_update.value
    if tz not in available_timezones():
        raise HTTPException(
            status_code=400,
            detail=f"Invalid timezone: {tz}. Must be a valid IANA timezone.")

    # Save setting
    set_setting(db, "timezone", tz, "System timezone for scheduling")

    return {
        "timezone":
        tz,
        "message":
        "Timezone updated. Restart Mantyx to apply changes to schedules."
    }


@router.get("/available-timezones")
def get_available_timezones():
    """Get list of available timezones grouped by region."""
    from zoneinfo import available_timezones

    timezones = sorted(available_timezones())

    # Group by region
    grouped = {}
    for tz in timezones:
        if '/' in tz:
            region = tz.split('/')[0]
            if region not in grouped:
                grouped[region] = []
            grouped[region].append(tz)

    return {
        "timezones": timezones,
        "grouped": grouped,
    }
