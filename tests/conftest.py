"""
Pytest configuration and fixtures for Mantyx tests.
"""

import os
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from mantyx.database import Base


@pytest.fixture
def temp_dir():
    """Create a temporary directory for tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def test_db():
    """Create a test database."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    engine = create_engine(f"sqlite:///{db_path}")
    Base.metadata.create_all(engine)

    TestingSessionLocal = sessionmaker(bind=engine)

    yield TestingSessionLocal

    # Cleanup
    Base.metadata.drop_all(engine)
    engine.dispose()
    os.unlink(db_path)


@pytest.fixture
def db_session(test_db):
    """Create a database session for a test."""
    session = test_db()
    try:
        yield session
    finally:
        session.close()
