"""
Schedule model for managing app scheduling configuration.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mantyx.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from mantyx.models.app import App


def get_default_timezone() -> str:
    """Get default timezone from settings or system detection."""
    # Try to get from database settings first
    try:
        from mantyx.database import get_db

        with get_db() as session:
            from mantyx.models.setting import Setting
            setting = session.query(Setting).filter(
                Setting.key == "timezone").first()
            if setting:
                return setting.value
    except Exception:
        # Database might not be initialized yet, or circular import
        pass

    # Fall back to system timezone
    from mantyx.config import get_system_timezone
    return get_system_timezone()


class Schedule(Base, TimestampMixin):
    """
    Represents a schedule configuration for a scheduled app.
    
    Supports cron expressions and interval-based scheduling.
    Each app can have multiple schedules.
    """

    __tablename__ = "schedules"

    # Primary key
    id: Mapped[int] = mapped_column(Integer,
                                    primary_key=True,
                                    autoincrement=True)

    # Foreign key to app
    app_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("apps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Schedule identification
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Schedule type: "cron" or "interval"
    schedule_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # Cron expression (if type is "cron")
    cron_expression: Mapped[Optional[str]] = mapped_column(String(100),
                                                           nullable=True)

    # Interval settings (if type is "interval")
    interval_seconds: Mapped[Optional[int]] = mapped_column(Integer,
                                                            nullable=True)

    # Timezone for schedule evaluation
    timezone: Mapped[str] = mapped_column(String(50),
                                          default=get_default_timezone)

    # State
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)

    # Execution tracking
    last_run: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    next_run: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    run_count: Mapped[int] = mapped_column(Integer, default=0)

    # Timeout settings
    timeout_seconds: Mapped[Optional[int]] = mapped_column(Integer,
                                                           nullable=True)

    # Misfire handling
    misfire_grace_time: Mapped[int] = mapped_column(Integer, default=60)
    coalesce: Mapped[bool] = mapped_column(Boolean, default=True)

    # Relationship
    app: Mapped["App"] = relationship("App", back_populates="schedules")

    def __repr__(self) -> str:
        return f"<Schedule(id={self.id}, app_id={self.app_id}, name='{self.name}')>"

    @property
    def schedule_display(self) -> str:
        """Get human-readable schedule description."""
        if self.schedule_type == "cron":
            return f"Cron: {self.cron_expression}"
        elif self.schedule_type == "interval":
            if self.interval_seconds:
                if self.interval_seconds >= 3600:
                    hours = self.interval_seconds // 3600
                    return f"Every {hours} hour{'s' if hours > 1 else ''}"
                elif self.interval_seconds >= 60:
                    minutes = self.interval_seconds // 60
                    return f"Every {minutes} minute{'s' if minutes > 1 else ''}"
                else:
                    return f"Every {self.interval_seconds} second{'s' if self.interval_seconds > 1 else ''}"
        return "Unknown schedule"
