"""
Logging utilities for Mantyx.

Provides structured logging to both database and files.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from mantyx.config import get_settings
from mantyx.models.log import LogEntry, LogLevel


class MantycLogger:
    """Enhanced logger that writes to both files and database."""

    def __init__(self, name: str):
        self.name = name
        self.logger = logging.getLogger(name)

        # Configure Python logger
        if not self.logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def _log_to_db(
        self,
        level: LogLevel,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Write log entry to database."""
        try:
            from mantyx.database import get_db

            with get_db() as session:
                entry = LogEntry(
                    app_id=app_id,
                    level=level,
                    source=self.name,
                    message=message,
                    details=details,
                    execution_id=execution_id,
                )
                session.add(entry)
        except Exception as e:
            # Don't let logging failures crash the app
            self.logger.error(f"Failed to write log to database: {e}")

    def debug(
        self,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Log debug message."""
        self.logger.debug(message)
        self._log_to_db(LogLevel.DEBUG, message, details, app_id, execution_id)

    def info(
        self,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Log info message."""
        self.logger.info(message)
        self._log_to_db(LogLevel.INFO, message, details, app_id, execution_id)

    def warning(
        self,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Log warning message."""
        self.logger.warning(message)
        self._log_to_db(LogLevel.WARNING, message, details, app_id, execution_id)

    def error(
        self,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Log error message."""
        self.logger.error(message)
        self._log_to_db(LogLevel.ERROR, message, details, app_id, execution_id)

    def critical(
        self,
        message: str,
        details: str | None = None,
        app_id: int | None = None,
        execution_id: int | None = None,
    ) -> None:
        """Log critical message."""
        self.logger.critical(message)
        self._log_to_db(LogLevel.CRITICAL, message, details, app_id, execution_id)


def get_logger(name: str) -> MantycLogger:
    """Get a logger instance."""
    return MantycLogger(name)


def get_app_log_path(app_name: str, execution_id: int | None = None) -> tuple[Path, Path]:
    """Get paths for app stdout and stderr logs."""
    settings = get_settings()
    log_dir = settings.logs_dir / app_name
    log_dir.mkdir(parents=True, exist_ok=True)

    if execution_id:
        stdout_path = log_dir / f"execution_{execution_id}_stdout.log"
        stderr_path = log_dir / f"execution_{execution_id}_stderr.log"
    else:
        # For perpetual apps, use current date
        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        stdout_path = log_dir / f"{date_str}_stdout.log"
        stderr_path = log_dir / f"{date_str}_stderr.log"

    return stdout_path, stderr_path
