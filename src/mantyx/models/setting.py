"""
Setting model for storing application-wide configuration.
"""

from typing import Optional

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from mantyx.models.base import Base, TimestampMixin


class Setting(Base, TimestampMixin):
    """
    Represents a system setting (key-value pairs).
    Used for user-configurable options like timezone, etc.
    """

    __tablename__ = "settings"

    # Primary key is the setting key
    key: Mapped[str] = mapped_column(String(100), primary_key=True)

    # Setting value
    value: Mapped[str] = mapped_column(String(500), nullable=False)

    # Optional description
    description: Mapped[Optional[str]] = mapped_column(String(500),
                                                       nullable=True)

    def __repr__(self) -> str:
        return f"<Setting(key='{self.key}', value='{self.value}')>"
