"""
Tests for safe app updates (ZIP and Git): dependencies are installed from the
staged new source before it replaces the live one, and a failed update leaves
the old source live, the version unchanged, and the app restarted.
"""

from unittest.mock import MagicMock
from zipfile import ZipFile

import pytest
from git import Actor, Repo

import mantyx.config as config_module
import mantyx.database as database_module
from mantyx.config import init_settings
from mantyx.core.app_manager import AppManager
from mantyx.database import get_db, init_db
from mantyx.models.app import App, AppState, AppType

AUTHOR = Actor("Test", "test@example.com")


@pytest.fixture
def instance(tmp_path):
    """Point a fresh Mantyx settings/DB singleton at an isolated temp directory."""
    settings = init_settings(base_dir=tmp_path / "mantyx_base", database_url=None)
    settings.ensure_directories()
    init_db()

    yield settings

    database_module.dispose_engine()
    config_module._settings = None


@pytest.fixture
def manager(instance):
    return AppManager(venv_manager=MagicMock(), supervisor=MagicMock(), scheduler=MagicMock())


def _make_app(name="demoapp", state=AppState.RUNNING, **fields):
    app = App(
        name=name,
        display_name=name,
        app_type=AppType.PERPETUAL,
        state=state,
        entrypoint="main.py",
        version="1.0.0",
        **fields,
    )
    with get_db() as session:
        session.add(app)
        session.commit()
        session.refresh(app)
        return app.id


def _get_app(app_id):
    with get_db() as session:
        app = session.query(App).filter(App.id == app_id).first()
        session.expunge(app)
        return app


def _write_old_source(settings, name="demoapp"):
    source_dir = settings.apps_dir / name / "app"
    source_dir.mkdir(parents=True)
    (source_dir / "main.py").write_text("print('old')\n")
    return source_dir


def _make_update_zip(tmp_path):
    zip_path = tmp_path / "update.zip"
    with ZipFile(zip_path, "w") as zf:
        zf.writestr("main.py", "print('new')\n")
        zf.writestr("requirements.txt", "onnxruntime\n")
    return zip_path


def _assert_no_leftovers(settings, name="demoapp"):
    assert not (settings.temp_dir / f"{name}_update").exists()
    assert not (settings.apps_dir / name / "app.previous").exists()


# ── ZIP updates ──────────────────────────────────────────────────────────────


def test_zip_update_installs_new_requirements_before_swapping_source(instance, manager, tmp_path):
    """Deps come from the staged requirements.txt while the old source is still live."""
    source_dir = _write_old_source(instance)
    app_id = _make_app()

    def check_install(app_name, requirements_file, on_log=None):
        assert requirements_file.parent == instance.temp_dir / "demoapp_update"
        assert requirements_file.read_text() == "onnxruntime\n"
        assert (source_dir / "main.py").read_text() == "print('old')\n"

    manager.venv_manager.install_requirements.side_effect = check_install

    result = manager.update_app_from_zip(app_id, _make_update_zip(tmp_path))

    manager.venv_manager.install_requirements.assert_called_once()
    assert (source_dir / "main.py").read_text() == "print('new')\n"
    assert result["new_version"] == "1.0.1"
    assert _get_app(app_id).version == "1.0.1"
    manager.supervisor.start_app.assert_called_once_with(app_id)
    _assert_no_leftovers(instance)


def test_zip_update_dependency_failure_rolls_back(instance, manager, tmp_path):
    """A failed dep install keeps the old source and version, and restarts the app."""
    source_dir = _write_old_source(instance)
    app_id = _make_app(state=AppState.RUNNING)
    manager.venv_manager.install_requirements.side_effect = RuntimeError("pip exploded")
    logs: list[str] = []

    with pytest.raises(RuntimeError, match="pip exploded"):
        manager.update_app_from_zip(app_id, _make_update_zip(tmp_path), on_log=logs.append)

    assert (source_dir / "main.py").read_text() == "print('old')\n"
    assert not (source_dir / "requirements.txt").exists()
    app = _get_app(app_id)
    assert app.version == "1.0.0"
    assert app.update_count == 0
    manager.supervisor.stop_app.assert_called_once()
    manager.supervisor.start_app.assert_called_once_with(app_id)
    assert any("keeping previous version 1.0.0" in line for line in logs)
    _assert_no_leftovers(instance)
    # The backup taken at the start of the update is still there.
    assert list((instance.backups_dir / "demoapp").glob("*/app/main.py"))


def test_zip_update_failure_does_not_start_app_that_was_not_running(instance, manager, tmp_path):
    _write_old_source(instance)
    app_id = _make_app(state=AppState.STOPPED)
    manager.venv_manager.install_requirements.side_effect = RuntimeError("pip exploded")

    with pytest.raises(RuntimeError):
        manager.update_app_from_zip(app_id, _make_update_zip(tmp_path))

    manager.supervisor.stop_app.assert_not_called()
    manager.supervisor.start_app.assert_not_called()


def test_zip_update_failure_after_swap_restores_old_source(
    instance, manager, tmp_path, monkeypatch
):
    """If recording the new version fails after the swap, the swap is undone."""
    source_dir = _write_old_source(instance)
    app_id = _make_app()

    def boom(current, old_version):
        raise RuntimeError("db write failed")

    monkeypatch.setattr(AppManager, "_next_version", staticmethod(boom))

    with pytest.raises(RuntimeError, match="db write failed"):
        manager.update_app_from_zip(app_id, _make_update_zip(tmp_path))

    assert (source_dir / "main.py").read_text() == "print('old')\n"
    assert _get_app(app_id).version == "1.0.0"
    manager.supervisor.start_app.assert_called_once_with(app_id)
    _assert_no_leftovers(instance)


# ── Git updates ──────────────────────────────────────────────────────────────


@pytest.fixture
def git_app(instance, tmp_path):
    """An app cloned from a local origin repo that has one new commit pending."""
    origin_dir = tmp_path / "origin"
    origin = Repo.init(origin_dir, initial_branch="main")
    (origin_dir / "main.py").write_text("print('old')\n")
    origin.index.add(["main.py"])
    old_commit = origin.index.commit("initial", author=AUTHOR, committer=AUTHOR).hexsha

    source_dir = instance.apps_dir / "demoapp" / "app"
    Repo.clone_from(str(origin_dir), source_dir, branch="main").close()

    (origin_dir / "main.py").write_text("print('new')\n")
    (origin_dir / "requirements.txt").write_text("onnxruntime\n")
    origin.index.add(["main.py", "requirements.txt"])
    new_commit = origin.index.commit("update", author=AUTHOR, committer=AUTHOR).hexsha
    origin.close()

    app_id = _make_app(git_url=str(origin_dir), git_branch="main", git_commit=old_commit)
    return {
        "app_id": app_id,
        "source_dir": source_dir,
        "old_commit": old_commit,
        "new_commit": new_commit,
    }


def _head(source_dir):
    repo = Repo(source_dir)
    try:
        return repo.head.commit.hexsha
    finally:
        repo.close()


def test_git_update_installs_new_requirements_before_swapping_source(instance, manager, git_app):
    source_dir = git_app["source_dir"]

    def check_install(app_name, requirements_file, on_log=None):
        assert requirements_file.parent == instance.temp_dir / "demoapp_update"
        assert (source_dir / "main.py").read_text() == "print('old')\n"

    manager.venv_manager.install_requirements.side_effect = check_install

    result = manager.pull_git_app(git_app["app_id"])

    manager.venv_manager.install_requirements.assert_called_once()
    assert result["changed"] is True
    assert result["new_version"] == "1.0.1"
    assert _head(source_dir) == git_app["new_commit"]
    assert (source_dir / "main.py").read_text() == "print('new')\n"
    app = _get_app(git_app["app_id"])
    assert app.version == "1.0.1"
    assert app.git_commit == git_app["new_commit"]
    manager.supervisor.start_app.assert_called_once_with(git_app["app_id"])
    _assert_no_leftovers(instance)


def test_git_update_dependency_failure_rolls_back(instance, manager, git_app):
    source_dir = git_app["source_dir"]
    manager.venv_manager.install_requirements.side_effect = RuntimeError("pip exploded")

    with pytest.raises(RuntimeError, match="pip exploded"):
        manager.pull_git_app(git_app["app_id"])

    assert _head(source_dir) == git_app["old_commit"]
    assert (source_dir / "main.py").read_text() == "print('old')\n"
    app = _get_app(git_app["app_id"])
    assert app.version == "1.0.0"
    assert app.git_commit == git_app["old_commit"]
    manager.supervisor.start_app.assert_called_once_with(git_app["app_id"])
    _assert_no_leftovers(instance)


def test_git_update_without_new_commits_restarts_and_keeps_version(instance, manager, git_app):
    manager.pull_git_app(git_app["app_id"])
    manager.supervisor.start_app.reset_mock()
    manager.venv_manager.install_requirements.reset_mock()

    result = manager.pull_git_app(git_app["app_id"])

    assert result["changed"] is False
    assert result["new_version"] == result["old_version"] == "1.0.1"
    manager.venv_manager.install_requirements.assert_not_called()
    manager.supervisor.start_app.assert_called_once_with(git_app["app_id"])
    _assert_no_leftovers(instance)


# ── Venv rebuild ─────────────────────────────────────────────────────────────


def test_rebuild_app_venv_stops_rebuilds_and_restarts(instance, manager):
    source_dir = _write_old_source(instance)
    (source_dir / "requirements.txt").write_text("requests\n")
    app_id = _make_app(state=AppState.RUNNING)

    manager.rebuild_app_venv(app_id)

    manager.supervisor.stop_app.assert_called_once()
    manager.venv_manager.rebuild.assert_called_once_with(
        "demoapp", source_dir / "requirements.txt", on_log=None
    )
    manager.supervisor.start_app.assert_called_once_with(app_id)


def test_rebuild_app_venv_failure_leaves_app_stopped(instance, manager):
    _write_old_source(instance)
    app_id = _make_app(state=AppState.RUNNING)
    manager.venv_manager.rebuild.side_effect = RuntimeError("no network")

    with pytest.raises(RuntimeError, match="no network"):
        manager.rebuild_app_venv(app_id)

    manager.supervisor.start_app.assert_not_called()
