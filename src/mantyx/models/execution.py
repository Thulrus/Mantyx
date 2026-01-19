"""
Execution model for tracking app run history.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mantyx.models.base import Base

if TYPE_CHECKING:
    from mantyx.models.app import App


class ExecutionStatus(str, enum.Enum):
    """Execution status values."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class Execution(Base):
    """
    Represents a single execution of an application.

    Tracks when apps run, how long they take, and their exit status.
    Used for both scheduled jobs and perpetual service restarts.
    """

    __tablename__ = "executions"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Foreign key to app
    app_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("apps.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Execution details
    status: Mapped[ExecutionStatus] = mapped_column(
        Enum(ExecutionStatus),
        nullable=False,
        default=ExecutionStatus.PENDING,
        index=True,
    )

    # Timing
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    # Process information
    pid: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_code: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Output capture
    stdout_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stderr_path: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Error information
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Trigger information
    trigger_type: Mapped[str] = mapped_column(
        String(50),
        default="manual",
        nullable=False,
    )
    trigger_details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Relationship
    app: Mapped["App"] = relationship("App", back_populates="executions")

    def __repr__(self) -> str:
        return f"<Execution(id={self.id}, app_id={self.app_id}, status={self.status.value})>"

    @property
    def duration_seconds(self) -> float | None:
        """Calculate execution duration in seconds."""
        if self.started_at and self.ended_at:
            return (self.ended_at - self.started_at).total_seconds()
        return None

    @property
    def is_active(self) -> bool:
        """Check if execution is still active."""
        return self.status in (ExecutionStatus.PENDING, ExecutionStatus.RUNNING)
