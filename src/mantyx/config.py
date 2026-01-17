"""
Configuration management for Mantyx.

Handles loading and validating configuration from environment
variables and configuration files.
"""

from datetime import datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def get_system_timezone() -> str:
    """Detect the system timezone."""
    try:
        # Try to get local timezone name
        import time
        if hasattr(time, 'tzname') and time.tzname:
            # This gives us something like ('EST', 'EDT')
            # We want a proper IANA timezone name
            pass

        # Better approach: use datetime to detect timezone
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz and hasattr(local_tz, 'key'):
            # type: ignore - tzinfo doesn't officially have 'key' but ZoneInfo does
            return local_tz.key  # type: ignore

        # Fallback to reading /etc/timezone on Linux
        try:
            with open('/etc/timezone', 'r', encoding='utf-8') as f:
                tz = f.read().strip()
                if tz:
                    # Validate it's a valid timezone
                    ZoneInfo(tz)
                    return tz
        except (FileNotFoundError, OSError):
            pass

        # Another fallback: symlink /etc/localtime
        try:
            import os
            localtime_path = os.path.realpath('/etc/localtime')
            if 'zoneinfo/' in localtime_path:
                tz = localtime_path.split('zoneinfo/')[-1]
                ZoneInfo(tz)
                return tz
        except (OSError, ValueError):
            pass

    except Exception:
        pass

    # Ultimate fallback
    return "UTC"


class Settings(BaseSettings):
    """Application settings loaded from environment or config file."""

    model_config = SettingsConfigDict(
        env_prefix="MANTYX_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Base paths
    base_dir: Path = Field(
        default=Path("/srv/mantyx"),
        description="Base directory for all Mantyx data",
    )

    # Database
    database_url: Optional[str] = Field(
        default=None,
        description="Database URL. Defaults to SQLite in data directory",
    )

    # Server settings
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8420, description="Server bind port")
    debug: bool = Field(default=False, description="Enable debug mode")

    # Upload limits
    max_upload_size_mb: int = Field(
        default=100,
        description="Maximum upload size in megabytes",
    )

    # App settings
    default_restart_delay: int = Field(
        default=5,
        description="Default delay between restart attempts (seconds)",
    )
    default_max_restarts: int = Field(
        default=3,
        description="Default maximum restart attempts before marking failed",
    )
    restart_window: int = Field(
        default=300,
        description="Time window for counting restarts (seconds)",
    )

    # Health check settings
    health_check_interval: int = Field(
        default=30,
        description="Interval between health checks (seconds)",
    )
    health_check_timeout: int = Field(
        default=10,
        description="Health check timeout (seconds)",
    )

    # Log retention
    log_retention_days: int = Field(
        default=30,
        description="Number of days to retain logs",
    )

    # Backup settings
    backup_retention_count: int = Field(
        default=5,
        description="Number of backups to retain per app",
    )

    # Timezone settings
    timezone: str = Field(
        default_factory=get_system_timezone,
        description="System timezone (auto-detected)",
    )

    @field_validator("base_dir", mode="before")
    @classmethod
    def validate_base_dir(cls, v):
        """Convert string to Path if needed."""
        if isinstance(v, str):
            return Path(v)
        return v

    @property
    def apps_dir(self) -> Path:
        """Directory containing app installations."""
        return self.base_dir / "apps"

    @property
    def venvs_dir(self) -> Path:
        """Directory containing virtual environments."""
        return self.base_dir / "venvs"

    @property
    def logs_dir(self) -> Path:
        """Directory containing app logs."""
        return self.base_dir / "logs"

    @property
    def backups_dir(self) -> Path:
        """Directory containing app backups."""
        return self.base_dir / "backups"

    @property
    def data_dir(self) -> Path:
        """Directory containing database and persistent data."""
        return self.base_dir / "data"

    @property
    def config_dir(self) -> Path:
        """Directory containing configuration files."""
        return self.base_dir / "config"

    @property
    def temp_dir(self) -> Path:
        """Directory for temporary files during uploads/updates."""
        return self.base_dir / "temp"

    @property
    def db_path(self) -> Path:
        """Path to SQLite database file."""
        return self.data_dir / "mantyx.db"

    @property
    def effective_database_url(self) -> str:
        """Get the effective database URL."""
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.db_path}"

    @property
    def max_upload_size_bytes(self) -> int:
        """Maximum upload size in bytes."""
        return self.max_upload_size_mb * 1024 * 1024

    def ensure_directories(self) -> None:
        """Create all required directories if they don't exist."""
        directories = [
            self.base_dir,
            self.apps_dir,
            self.venvs_dir,
            self.logs_dir,
            self.backups_dir,
            self.data_dir,
            self.config_dir,
            self.temp_dir,
        ]
        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)


# Global settings instance
_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get the global settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings


def init_settings(**kwargs) -> Settings:
    """Initialize settings with custom values."""
    global _settings
    _settings = Settings(**kwargs)
    return _settings
