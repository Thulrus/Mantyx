"""
Tests for full-instance backup export/import (BackupManager).
"""

from unittest.mock import MagicMock, patch
from zipfile import ZipFile

import pytest

import mantyx.app as mantyx_app
import mantyx.config as config_module
import mantyx.database as database_module
from mantyx.config import init_settings
from mantyx.core.backup_manager import BackupManager
from mantyx.database import get_db, init_db
from mantyx.models.app import App, AppState, AppType
from mantyx.models.setting import Setting


@pytest.fixture
def instance(tmp_path):
    """Point a fresh Mantyx settings/DB singleton at an isolated temp directory."""
    base_dir = tmp_path / "mantyx_base"
    settings = init_settings(base_dir=base_dir, database_url=None)
    settings.ensure_directories()
    init_db()

    yield settings

    # Teardown: don't leak the isolated engine/settings/scheduler into other tests.
    database_module.dispose_engine()
    config_module._settings = None
    if mantyx_app.scheduler is not None:
        mantyx_app.scheduler.stop()
    mantyx_app.scheduler = None
    mantyx_app.supervisor = None


def _make_app(name="demoapp", state=AppState.ENABLED, app_type=AppType.SCHEDULED):
    app = App(
        name=name,
        display_name=name,
        app_type=app_type,
        state=state,
        entrypoint="main.py",
        version="1.0.0",
    )
    with get_db() as session:
        session.add(app)
        session.commit()
        session.refresh(app)
        app_id = app.id
    return app_id


def _write_app_source(settings, name="demoapp"):
    source_dir = settings.apps_dir / name / "app"
    source_dir.mkdir(parents=True, exist_ok=True)
    (source_dir / "main.py").write_text("print('hello')\n")
    (source_dir / "requirements.txt").write_text("")

    data_dir = settings.apps_dir / name / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "state.txt").write_text("persisted-value\n")


def test_create_backup_rejects_non_sqlite_backend(instance):
    config_module._settings = None
    init_settings(base_dir=instance.base_dir, database_url="postgresql://example/db")

    manager = BackupManager(venv_manager=MagicMock())
    with pytest.raises(ValueError, match="SQLite"):
        manager.create_backup()


def test_create_backup_contains_expected_files(instance):
    _make_app()
    _write_app_source(instance)

    with get_db() as session:
        session.add(Setting(key="timezone", value="America/New_York"))
        session.commit()

    manager = BackupManager(venv_manager=MagicMock())
    zip_path = manager.create_backup()

    try:
        assert zip_path.exists()
        with ZipFile(zip_path) as zf:
            names = set(zf.namelist())
            assert "manifest.json" in names
            assert "database.db" in names
            assert "apps/demoapp/app/main.py" in names
            assert "apps/demoapp/data/state.txt" in names
    finally:
        zip_path.unlink(missing_ok=True)


def test_restore_backup_replaces_current_state(instance):
    _make_app(name="demoapp")
    _write_app_source(instance, name="demoapp")
    with get_db() as session:
        session.add(Setting(key="timezone", value="America/New_York"))
        session.commit()

    manager = BackupManager(venv_manager=MagicMock())
    zip_path = manager.create_backup()

    # Simulate state changing after the backup was taken: a new app appears
    # that should NOT survive the restore.
    _make_app(name="junkapp")
    _write_app_source(instance, name="junkapp")

    with (
        patch("mantyx.core.backup_manager.ProcessSupervisor") as MockSupervisor,
        patch("mantyx.core.scheduler.AppScheduler") as MockScheduler,
    ):
        MockSupervisor.return_value = MagicMock()
        MockScheduler.return_value = MagicMock()

        try:
            result = manager.restore_backup(zip_path)
        finally:
            zip_path.unlink(missing_ok=True)

    assert result["app_count"] == 1

    with get_db() as session:
        names = {a.name for a in session.query(App).all()}
        assert names == {"demoapp"}

        tz_setting = session.query(Setting).filter(Setting.key == "timezone").first()
        assert tz_setting is not None
        assert tz_setting.value == "America/New_York"

    assert (instance.apps_dir / "demoapp" / "app" / "main.py").read_text() == "print('hello')\n"
    assert (instance.apps_dir / "demoapp" / "data" / "state.txt").exists()
    assert not (instance.apps_dir / "junkapp").exists()

    # restore_backup swaps in fresh scheduler/supervisor globals on mantyx.app
    assert mantyx_app.scheduler is MockScheduler.return_value
    assert mantyx_app.supervisor is MockSupervisor.return_value
