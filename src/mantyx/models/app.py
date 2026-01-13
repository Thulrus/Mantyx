"""
Application model representing managed Python applications.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Enum, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mantyx.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from mantyx.models.execution import Execution
    from mantyx.models.schedule import Schedule
    from mantyx.models.log import LogEntry


class AppState(str, enum.Enum):
    """Application lifecycle states."""
    
    UPLOADED = "uploaded"
    INSTALLED = "installed"
    ENABLED = "enabled"
    DISABLED = "disabled"
    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"
    DELETED = "deleted"


class AppType(str, enum.Enum):
    """Application execution types."""
    
    SCHEDULED = "scheduled"
    PERPETUAL = "perpetual"


class App(Base, TimestampMixin):
    """
    Represents a managed Python application.
    
    Each app has its own directory, virtual environment, and lifecycle state.
    Apps can be either scheduled (run periodically) or perpetual (long-running services).
    """
    
    __tablename__ = "apps"
    
    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    
    # Basic information
    name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    # Type and state
    app_type: Mapped[AppType] = mapped_column(Enum(AppType), nullable=False)
    state: Mapped[AppState] = mapped_column(
        Enum(AppState),
        nullable=False,
        default=AppState.UPLOADED,
        index=True,
    )
    
    # Versioning
    version: Mapped[str] = mapped_column(String(50), default="1.0.0")
    
    # Paths (relative to apps directory)
    entrypoint: Mapped[str] = mapped_column(String(255), nullable=False)
    
    # Configuration
    config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    environment: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    
    # Process settings (for perpetual apps)
    restart_policy: Mapped[str] = mapped_column(String(50), default="on-failure")
    max_restarts: Mapped[int] = mapped_column(Integer, default=3)
    restart_delay: Mapped[int] = mapped_column(Integer, default=5)
    
    # Health check settings
    health_check_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    health_check_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    health_check_interval: Mapped[int] = mapped_column(Integer, default=30)
    
    # Web interface URL (if app provides one)
    web_url: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    web_port: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # Runtime state (updated by supervisor)
    pid: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    last_restart_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    last_health_check: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    health_status: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)
    
    # Error tracking
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    last_error_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    # Soft delete
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted_at: Mapped[Optional[datetime]] = mapped_column(nullable=True)
    
    # Git source (optional)
    git_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    git_branch: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    git_commit: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    
    # Relationships
    executions: Mapped[list["Execution"]] = relationship(
        "Execution",
        back_populates="app",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    schedules: Mapped[list["Schedule"]] = relationship(
        "Schedule",
        back_populates="app",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    logs: Mapped[list["LogEntry"]] = relationship(
        "LogEntry",
        back_populates="app",
        cascade="all, delete-orphan",
        lazy="dynamic",
    )
    
    def __repr__(self) -> str:
        return f"<App(id={self.id}, name='{self.name}', state={self.state.value})>"
    
    @property
    def is_running(self) -> bool:
        """Check if the app is currently running."""
        return self.state == AppState.RUNNING and self.pid is not None
    
    @property
    def can_start(self) -> bool:
        """Check if the app can be started."""
        return self.state in (AppState.ENABLED, AppState.STOPPED, AppState.FAILED)
    
    @property
    def can_stop(self) -> bool:
        """Check if the app can be stopped."""
        return self.state == AppState.RUNNING
    
    @property
    def can_enable(self) -> bool:
        """Check if the app can be enabled."""
        return self.state in (AppState.INSTALLED, AppState.DISABLED)
    
    @property
    def can_disable(self) -> bool:
        """Check if the app can be disabled."""
        return self.state in (AppState.ENABLED, AppState.STOPPED, AppState.FAILED)
