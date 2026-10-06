"""
Database session management and initialization.
"""

from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mantyx.config import get_settings
from mantyx.models.base import Base

# Sync engine and session factory
_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None

# How long a SQLite connection waits for a competing writer before raising
# "database is locked". Mantyx writes from several threads (API, scheduler,
# supervisor monitor), so short lock waits are normal and must not error out.
SQLITE_BUSY_TIMEOUT_SECONDS = 30


def init_db() -> None:
    """Initialize the database engine, create tables, and patch up older schemas."""
    global _engine, _SessionLocal

    settings = get_settings()
    url = settings.effective_database_url
    is_sqlite = url.startswith("sqlite")

    connect_args = {}
    if is_sqlite:
        connect_args = {"timeout": SQLITE_BUSY_TIMEOUT_SECONDS, "check_same_thread": False}

    engine = create_engine(
        url,
        echo=settings.debug,
        pool_pre_ping=True,
        connect_args=connect_args,
    )

    if is_sqlite:
        # Registered on this engine only (not the global Engine class), so
        # re-initializing after a backup restore doesn't stack up listeners.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    _engine = engine
    _SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    # Create any missing tables, then add columns that older installs lack.
    Base.metadata.create_all(bind=engine)
    if is_sqlite:
        ensure_schema(engine)


# Columns added after the first release. create_all() never alters existing
# tables, so installs created before these columns existed need them added.
# Each entry: (table, column, SQL type/default, optional backfill statement).
_ADDED_COLUMNS: list[tuple[str, str, str, str | None]] = [
    ("apps", "last_updated_at", "DATETIME", None),
    ("apps", "update_count", "INTEGER DEFAULT 0", None),
    (
        "apps",
        "web_port_source",
        "VARCHAR(20)",
        # Links that existed before auto-detection were set by hand.
        "UPDATE apps SET web_port_source = 'manual' "
        "WHERE web_url IS NOT NULL OR web_port IS NOT NULL",
    ),
]


def ensure_schema(engine: Engine) -> None:
    """Idempotently add columns that older databases are missing.

    Runs on every startup so a deploy never depends on migration scripts
    having been run by hand against the right database.
    """
    with engine.begin() as conn:
        for table, column, ddl, backfill in _ADDED_COLUMNS:
            existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
            if not existing or column in existing:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            if backfill:
                conn.execute(text(backfill))


def dispose_engine() -> None:
    """Dispose of the current engine and drop the session factory.

    Used before replacing the underlying SQLite file (e.g. during a backup
    restore) so no pooled connection keeps the old file open or locked.
    The next call to get_engine()/get_db() will lazily re-initialize against
    whatever file is at the configured path.
    """
    global _engine, _SessionLocal

    if _engine is not None:
        _engine.dispose()

    _engine = None
    _SessionLocal = None


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
