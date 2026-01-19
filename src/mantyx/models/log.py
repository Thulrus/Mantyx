"""
Log entry model for structured logging.
"""

import enum
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from mantyx.models.base import Base

if TYPE_CHECKING:
    from mantyx.models.app import App


class LogLevel(str, enum.Enum):
    """Log severity levels."""

    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class LogEntry(Base):
    """
    Represents a structured log entry.

    Used for system-level logging of app lifecycle events,
    not for capturing app stdout/stderr (which goes to files).
    """

    __tablename__ = "log_entries"

    # Primary key
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Optional foreign key to app (null for system logs)
    app_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("apps.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # Timestamp
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
        index=True,
    )

    # Log level
    level: Mapped[LogLevel] = mapped_column(
        Enum(LogLevel),
        nullable=False,
        default=LogLevel.INFO,
        index=True,
    )

    # Source component
    source: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    # Log message
    message: Mapped[str] = mapped_column(Text, nullable=False)

    # Additional context
    details: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Execution reference (if related to a specific execution)
    execution_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("executions.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationship
    app: Mapped[Optional["App"]] = relationship("App", back_populates="logs")

    def __repr__(self) -> str:
        return f"<LogEntry(id={self.id}, level={self.level.value}, source='{self.source}')>"
