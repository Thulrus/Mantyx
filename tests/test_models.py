"""
Basic tests for Mantyx models.
"""

from mantyx.models.app import App, AppState, AppType


def test_app_creation(db_session):
    """Test creating an app in the database."""
    app = App(
        name="Test App",
        display_name="Test App",
        app_type=AppType.PERPETUAL,
        state=AppState.UPLOADED,
        entrypoint="main.py",
    )
    db_session.add(app)
    db_session.commit()

    assert app.id is not None
    assert app.name == "Test App"
    assert app.app_type == AppType.PERPETUAL
    assert app.state == AppState.UPLOADED
    assert app.is_deleted is False


def test_app_soft_delete(db_session):
    """Test soft delete functionality."""
    app = App(
        name="Delete Test",
        display_name="Delete Test",
        app_type=AppType.SCHEDULED,
        state=AppState.UPLOADED,
        entrypoint="main.py",
    )
    db_session.add(app)
    db_session.commit()

    app_id = app.id

    # Soft delete
    app.is_deleted = True
    db_session.commit()

    # Should still exist in database
    deleted_app = db_session.query(App).filter(App.id == app_id).first()
    assert deleted_app is not None
    assert deleted_app.is_deleted is True
