"""
Pydantic schemas for API requests and responses.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from mantyx.models.app import AppState, AppType
from mantyx.models.execution import ExecutionStatus
from mantyx.models.log import LogLevel


# App schemas
class AppBase(BaseModel):
    display_name: str
    description: Optional[str] = None
    app_type: AppType
    entrypoint: str
    environment: Optional[dict[str, str]] = None
    restart_policy: str = "on-failure"
    max_restarts: int = 3
    restart_delay: int = 5
    health_check_enabled: bool = False
    health_check_url: Optional[str] = None
    web_url: Optional[str] = None
    web_port: Optional[int] = None


class AppCreate(AppBase):
    name: str


class AppUpdate(BaseModel):
    display_name: Optional[str] = None
    description: Optional[str] = None
    app_type: Optional[AppType] = None
    entrypoint: Optional[str] = None
    environment: Optional[dict[str, str]] = None
    restart_policy: Optional[str] = None
    max_restarts: Optional[int] = None
    restart_delay: Optional[int] = None
    health_check_enabled: Optional[bool] = None
    health_check_url: Optional[str] = None
    web_url: Optional[str] = None
    web_port: Optional[int] = None


class AppResponse(AppBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    name: str
    state: AppState
    version: str
    pid: Optional[int] = None
    restart_count: int = 0
    last_restart_at: Optional[datetime] = None
    last_health_check: Optional[datetime] = None
    health_status: Optional[str] = None
    last_error: Optional[str] = None
    last_error_at: Optional[datetime] = None
    git_url: Optional[str] = None
    git_branch: Optional[str] = None
    git_commit: Optional[str] = None
    created_at: datetime
    updated_at: datetime


# Schedule schemas
class ScheduleBase(BaseModel):
    name: str
    description: Optional[str] = None
    schedule_type: str
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    timezone: str = "UTC"
    timeout_seconds: Optional[int] = None
    misfire_grace_time: int = 60
    coalesce: bool = True


class ScheduleCreate(ScheduleBase):
    app_id: int


class ScheduleUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None
    timezone: Optional[str] = None
    is_enabled: Optional[bool] = None
    timeout_seconds: Optional[int] = None


class ScheduleResponse(ScheduleBase):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    app_id: int
    is_enabled: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    created_at: datetime
    updated_at: datetime


# Execution schemas
class ExecutionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    app_id: int
    status: ExecutionStatus
    started_at: Optional[datetime] = None
    ended_at: Optional[datetime] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    stdout_path: Optional[str] = None
    stderr_path: Optional[str] = None
    error_message: Optional[str] = None
    trigger_type: str
    trigger_details: Optional[str] = None


# Log schemas
class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    
    id: int
    app_id: Optional[int] = None
    timestamp: datetime
    level: LogLevel
    source: str
    message: str
    details: Optional[str] = None


# Upload schemas
class UploadResponse(BaseModel):
    app_id: int
    app_name: str
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
    uptime_seconds: Optional[float] = None
