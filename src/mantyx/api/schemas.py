"""
Pydantic schemas for API requests and responses.
"""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from mantyx.models.app import AppState, AppType
from mantyx.models.execution import ExecutionStatus
from mantyx.models.log import LogLevel


def get_default_timezone() -> str:
    """Get default timezone from settings or system detection."""
    # Try to get from database settings first
    try:
        from mantyx.database import get_db
        from mantyx.models.setting import Setting

        with get_db() as session:
            setting = session.query(Setting).filter(Setting.key == "timezone").first()
            if setting:
                return setting.value
    except Exception:
        # Database might not be initialized yet
        pass

    # Fall back to system timezone
    from mantyx.config import get_system_timezone

    return get_system_timezone()


# App schemas
class AppBase(BaseModel):
    display_name: str
    description: str | None = None
    app_type: AppType
    entrypoint: str
    environment: dict[str, str] | None = None
    restart_policy: str = "on-failure"
    max_restarts: int = 3
    restart_delay: int = 5
    health_check_enabled: bool = False
    health_check_url: str | None = None
    web_url: str | None = None
    web_port: int | None = None


class AppCreate(AppBase):
    name: str


class AppUpdate(BaseModel):
    display_name: str | None = None
    description: str | None = None
    app_type: AppType | None = None
    entrypoint: str | None = None
    environment: dict[str, str] | None = None
    restart_policy: str | None = None
    max_restarts: int | None = None
    restart_delay: int | None = None
    health_check_enabled: bool | None = None
    health_check_url: str | None = None
    web_url: str | None = None
    web_port: int | None = None


class AppResponse(AppBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    state: AppState
    version: str
    pid: int | None = None
    restart_count: int = 0
    last_restart_at: datetime | None = None
    last_health_check: datetime | None = None
    health_status: str | None = None
    last_error: str | None = None
    last_error_at: datetime | None = None
    git_url: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    created_at: datetime
    updated_at: datetime


# Schedule schemas
class ScheduleBase(BaseModel):
    name: str
    description: str | None = None
    schedule_type: str
    cron_expression: str | None = None
    interval_seconds: int | None = None
    timezone: str = Field(default_factory=get_default_timezone)
    timeout_seconds: int | None = None
    misfire_grace_time: int = 60
    coalesce: bool = True


class ScheduleCreate(ScheduleBase):
    app_id: int


class ScheduleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    cron_expression: str | None = None
    interval_seconds: int | None = None
    timezone: str | None = None
    is_enabled: bool | None = None
    timeout_seconds: int | None = None


class ScheduleResponse(ScheduleBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int
    is_enabled: bool
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


# Execution schemas
class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int
    status: ExecutionStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    pid: int | None = None
    exit_code: int | None = None
    stdout_path: str | None = None
    stderr_path: str | None = None
    error_message: str | None = None
    trigger_type: str
    trigger_details: str | None = None


# Log schemas
class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int | None = None
    timestamp: datetime
    level: LogLevel
    source: str
    message: str
    details: str | None = None


# Upload schemas
class UploadResponse(BaseModel):
    app_id: int
    app_name: str
    message: str


# Update schemas
class UpdateResponse(BaseModel):
    app_id: int
    app_name: str
    old_version: str
    new_version: str
    changed: bool = True
    backup_created: bool = True
    old_commit: str | None = None
    new_commit: str | None = None
    message: str


# Status schemas
class AppStatusResponse(BaseModel):
    app_id: int
    app_name: str
    state: AppState
    is_running: bool
    can_start: bool
    can_stop: bool
    can_enable: bool
    can_disable: bool
    uptime_seconds: float | None = None
