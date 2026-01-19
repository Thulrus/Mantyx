"""
Database session management and initialization.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mantyx.config import get_settings
from mantyx.models.base import Base

# Sync engine and session factory
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def init_db() -> None:
    """Initialize the database engine and create tables."""
    global _engine, _SessionLocal

    settings = get_settings()

    # Enable foreign key support for SQLite
    @event.listens_for(Engine, "connect")
    def set_sqlite_pragma(dbapi_conn, connection_record):
        if "sqlite" in settings.effective_database_url:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = create_engine(
        settings.effective_database_url,
        echo=settings.debug,
        pool_pre_ping=True,
    )

    _SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        bind=_engine,
    )

    # Create all tables
    Base.metadata.create_all(bind=_engine)


def get_engine() -> Engine:
    """Get the database engine."""
    if _engine is None:
        init_db()
    assert _engine is not None
    return _engine


def get_session_factory() -> sessionmaker[Session]:
    """Get the session factory."""
    if _SessionLocal is None:
        init_db()
    assert _SessionLocal is not None
    return _SessionLocal


@contextmanager
def get_db() -> Generator[Session, None, None]:
    """Get a database session context manager."""
    SessionLocal = get_session_factory()
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db_session():
    """Get a database session (for dependency injection).

    This is a generator that yields a session and ensures it's closed after use.
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
