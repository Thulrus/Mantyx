"""
Pydantic schemas for API requests and responses.
"""

import re
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, field_validator

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


def _as_local(dt: datetime | None) -> str | None:
    """Naive values written with datetime.now() are the server's local time."""
    if dt is None:
        return None
    return (dt.astimezone() if dt.tzinfo is None else dt).isoformat()


def _as_utc(dt: datetime | None) -> str | None:
    """Naive values from SQLite's CURRENT_TIMESTAMP default are UTC."""
    if dt is None:
        return None
    return (dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt).isoformat()


# Datetimes are always sent with an explicit offset so browsers in a different
# timezone than the server still show correct times.
LocalDateTime = Annotated[datetime, PlainSerializer(_as_local, return_type=str | None)]
UtcDateTime = Annotated[datetime, PlainSerializer(_as_utc, return_type=str | None)]


ENV_NAME_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    app_type: AppType | None = None
    entrypoint: str | None = None
    environment: dict[str, str] | None = None
    restart_policy: Literal["on-failure", "always", "never"] | None = None
    max_restarts: int | None = Field(default=None, ge=0, le=1000)
    restart_delay: int | None = Field(default=None, ge=0, le=3600)
    health_check_enabled: bool | None = None
    health_check_url: str | None = None
    web_url: str | None = Field(default=None, max_length=255)
    web_port: int | None = Field(default=None, ge=1, le=65535)

    @field_validator("environment")
    @classmethod
    def _check_env_names(cls, value):
        if value is None:
            return value
        for key in value:
            if not ENV_NAME_PATTERN.match(key):
                raise ValueError(
                    f"'{key}' isn't a valid variable name (letters, digits and _; "
                    "can't start with a digit)"
                )
        return value


class AppResponse(AppBase):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    state: AppState
    version: str
    pid: int | None = None
    restart_count: int = 0
    last_restart_at: LocalDateTime | None = None
    last_health_check: LocalDateTime | None = None
    health_status: str | None = None
    last_error: str | None = None
    last_error_at: LocalDateTime | None = None
    web_port_source: str | None = None
    git_url: str | None = None
    git_branch: str | None = None
    git_commit: str | None = None
    last_updated_at: LocalDateTime | None = None
    update_count: int | None = 0
    created_at: UtcDateTime
    updated_at: UtcDateTime

    # Derived, user-facing status (see mantyx.core.status). Filled in by the
    # list/detail endpoints; absent on responses that return the bare record.
    status: str | None = None
    status_label: str | None = None
    attention: bool = False
    enabled: bool | None = None
    next_run: str | None = None
    last_run: dict | None = None
    current_run: dict | None = None
    schedule_count: int = 0
    enabled_schedule_count: int = 0
    active_task: dict | None = None
    git_status: dict | None = None
    update_available: bool = False


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
    is_enabled: bool = True


class ScheduleUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    schedule_type: str | None = None
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
    last_run: LocalDateTime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    created_at: UtcDateTime
    updated_at: UtcDateTime


# Execution schemas
class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    app_id: int
    status: ExecutionStatus
    started_at: LocalDateTime | None = None
    ended_at: LocalDateTime | None = None
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
    timestamp: UtcDateTime
    level: LogLevel
    source: str
    message: str
    details: str | None = None


# Upload schemas
class UploadResponse(BaseModel):
    app_id: int
    app_name: str
    message: str


class TaskStartResponse(BaseModel):
    """Returned immediately when a long-running operation is kicked off."""

    task_id: str
    message: str


class TaskResponse(BaseModel):
    """Progress/log snapshot for a background operation, for polling."""

    task_id: str
    name: str
    app_id: int | None = None
    status: str
    logs: list[str]
    log_count: int
    steps: list[dict] = []
    error: str | None = None
    result: dict | None = None


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


class GitUpdateCheckResponse(BaseModel):
    app_id: int
    app_name: str
    update_available: bool
    commits_behind: int = 0
    local_commit: str
    remote_commit: str


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
