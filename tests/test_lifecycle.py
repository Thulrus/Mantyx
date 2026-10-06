"""
Tests for adding/removing apps, the HTTP API surface the web UI relies on,
log reading, retention, and upgrading databases from older Mantyx versions.
"""

import io
import json
import sqlite3
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

import mantyx.config as config_module
import mantyx.database as database_module
from mantyx.api.executions import read_log_chunk
from mantyx.config import init_settings
from mantyx.core import runtime
from mantyx.core.app_manager import AppManager, detect_entrypoint, safe_extract_zip
from mantyx.core.scheduler import AppScheduler
from mantyx.database import get_db, init_db
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus
from mantyx.models.log import LogEntry
from mantyx.models.schedule import Schedule


@pytest.fixture
def instance(tmp_path):
    settings = init_settings(base_dir=tmp_path / "mantyx_base", database_url=None)
    settings.ensure_directories()
    init_db()
    yield settings
    scheduler = runtime.get_scheduler()
    if scheduler:
        scheduler.stop()
    runtime.clear_runtime()
    database_module.dispose_engine()
    config_module._settings = None


@pytest.fixture
def manager(instance):
    venv = MagicMock()
    venv.get_venv_path.side_effect = lambda name: instance.venvs_dir / name
    return AppManager(venv_manager=venv, supervisor=MagicMock(), scheduler=MagicMock())


def _zip(tmp_path, files: dict[str, str], name="app.zip"):
    path = tmp_path / name
    with ZipFile(path, "w") as zf:
        for arcname, content in files.items():
            zf.writestr(arcname, content)
    return path


# ── ZIP handling ────────────────────────────────────────────────────────────


def test_zip_with_single_top_level_folder_is_flattened(tmp_path):
    dest = tmp_path / "out"
    safe_extract_zip(
        _zip(tmp_path, {"MyApp/main.py": "x", "MyApp/lib/util.py": "y", "__MACOSX/._main.py": "z"}),
        dest,
    )
    assert (dest / "main.py").exists()
    assert (dest / "lib" / "util.py").exists()
    assert not (dest / "MyApp").exists()
    assert not (dest / "__MACOSX").exists()


def test_zip_path_traversal_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="Invalid path"):
        safe_extract_zip(_zip(tmp_path, {"../evil.py": "x"}), tmp_path / "out")


def test_zip_filenames_with_double_dots_are_allowed(tmp_path):
    dest = tmp_path / "out"
    safe_extract_zip(_zip(tmp_path, {"main.py": "x", "notes..txt": "y"}), dest)
    assert (dest / "notes..txt").exists()


def test_entrypoint_detection_prefers_main_guard_and_previous_choice(tmp_path):
    (tmp_path / "helpers.py").write_text("def f(): pass\n")
    (tmp_path / "script.py").write_text("if __name__ == '__main__':\n    pass\n")
    assert detect_entrypoint(tmp_path) == "script.py"
    assert detect_entrypoint(tmp_path, preferred="helpers.py") == "helpers.py"
    assert detect_entrypoint(tmp_path, preferred="gone.py") == "script.py"


# ── names and deletion ──────────────────────────────────────────────────────


@pytest.mark.parametrize("bad", ["../escape", "My App", "", "-lead", "a" * 70, "x/y"])
def test_invalid_app_ids_are_rejected(manager, tmp_path, bad):
    with pytest.raises(ValueError):
        manager.create_app_from_zip(_zip(tmp_path, {"main.py": "x"}), bad, "Display")


def test_reusing_a_soft_deleted_name_starts_clean(instance, manager, tmp_path):
    manager.create_app_from_zip(_zip(tmp_path, {"main.py": "old", "stale.py": "x"}), "demo", "Demo")
    with get_db() as session:
        app = session.query(App).filter(App.name == "demo").first()
        app.is_deleted = True  # how older Mantyx versions deleted apps
        app.state = AppState.DELETED

    manager.create_app_from_zip(_zip(tmp_path, {"main.py": "new"}, "v2.zip"), "demo", "Demo")

    source = instance.apps_dir / "demo" / "app"
    assert (source / "main.py").read_text() == "new"
    assert not (source / "stale.py").exists()


def test_leftover_files_without_a_record_are_moved_aside_not_deleted(instance, manager, tmp_path):
    leftover = instance.apps_dir / "demo" / "data"
    leftover.mkdir(parents=True)
    (leftover / "precious.db").write_text("keep me")

    manager.create_app_from_zip(_zip(tmp_path, {"main.py": "x"}), "demo", "Demo")

    saved = list((instance.backups_dir / "demo").glob("orphaned-*/data/precious.db"))
    assert saved and saved[0].read_text() == "keep me"


def test_delete_removes_record_files_and_schedules(instance, manager, tmp_path):
    result = manager.create_app_from_zip(
        _zip(tmp_path, {"main.py": "x"}), "demo", "Demo", app_type=AppType.SCHEDULED
    )
    app_id = result["id"]
    with get_db() as session:
        session.add(
            Schedule(app_id=app_id, name="s", schedule_type="interval", interval_seconds=60)
        )
        session.add(Execution(app_id=app_id, status=ExecutionStatus.SUCCESS))
        session.flush()
        schedule_id = session.query(Schedule.id).scalar()
    (instance.logs_dir / "demo").mkdir(parents=True)

    manager.delete_app(app_id)

    with get_db() as session:
        assert session.query(App).count() == 0
        assert session.query(Schedule).count() == 0
        assert session.query(Execution).count() == 0
    assert not (instance.apps_dir / "demo").exists()
    assert not (instance.logs_dir / "demo").exists()
    manager.scheduler.remove_schedule.assert_called_once_with(schedule_id)


# ── API ─────────────────────────────────────────────────────────────────────


@pytest.fixture
def client_no_lifespan(instance):
    from mantyx.app import app as fastapi_app

    scheduler = AppScheduler()
    scheduler.start()
    runtime.set_runtime(scheduler=scheduler, supervisor=MagicMock())
    yield TestClient(fastapi_app)


def _add_app(name="demo", app_type=AppType.SCHEDULED, state=AppState.ENABLED, **fields):
    with get_db() as session:
        app = App(
            name=name,
            display_name=name.title(),
            app_type=app_type,
            state=state,
            entrypoint="main.py",
            **fields,
        )
        session.add(app)
        session.flush()
        return app.id


def test_app_list_includes_plain_status(client_no_lifespan):
    c = client_no_lifespan
    _add_app("job", AppType.SCHEDULED, AppState.ENABLED)
    _add_app("svc", AppType.PERPETUAL, AppState.FAILED, last_error="boom")
    _add_app("fresh", AppType.PERPETUAL, AppState.UPLOADED)

    apps = {a["name"]: a for a in c.get("/api/apps").json()}

    assert apps["job"]["status"] == "no_schedule" and apps["job"]["attention"]
    assert apps["svc"]["status"] == "failed" and apps["svc"]["status_label"] == "Failed"
    assert apps["fresh"]["status"] == "not_installed"


def test_schedule_api_validates_and_reports_next_run(client_no_lifespan):
    c = client_no_lifespan
    app_id = _add_app()

    bad = c.post(
        "/api/schedules",
        json={"app_id": app_id, "name": "x", "schedule_type": "cron", "cron_expression": "nope"},
    )
    assert bad.status_code == 400

    created = c.post(
        "/api/schedules",
        json={
            "app_id": app_id,
            "name": "Weekdays",
            "schedule_type": "cron",
            "cron_expression": "30 6 * * mon-fri",
        },
    )
    assert created.status_code == 200
    body = created.json()
    assert body["next_run"] is not None

    # Switching type is honoured (previously silently ignored).
    changed = c.patch(
        f"/api/schedules/{body['id']}", json={"schedule_type": "interval", "interval_seconds": 600}
    )
    assert changed.status_code == 200
    assert changed.json()["schedule_type"] == "interval"
    assert changed.json()["cron_expression"] is None

    app = c.get(f"/api/apps/{app_id}").json()
    assert app["status"] == "scheduled" and app["next_run"]


def test_schedule_cannot_be_added_to_always_running_app(client_no_lifespan):
    app_id = _add_app(app_type=AppType.PERPETUAL)
    r = client_no_lifespan.post(
        "/api/schedules",
        json={"app_id": app_id, "name": "x", "schedule_type": "interval", "interval_seconds": 60},
    )
    assert r.status_code == 400


def test_schedule_preview(client_no_lifespan):
    r = client_no_lifespan.post(
        "/api/schedules/preview",
        json={"schedule_type": "cron", "cron_expression": "0 9 * * sat", "count": 2},
    )
    assert r.status_code == 200
    runs = r.json()["next_runs"]
    assert len(runs) == 2
    assert all(datetime.fromisoformat(t).strftime("%a") == "Sat" for t in runs)


def test_timezone_update_applies_to_scheduler_immediately(client_no_lifespan):
    r = client_no_lifespan.put("/api/settings/timezone", json={"value": "Europe/Paris"})
    assert r.status_code == 200
    assert runtime.get_scheduler().timezone == "Europe/Paris"


def test_upload_rejects_bad_id_and_duplicates(client_no_lifespan):
    c = client_no_lifespan
    files = {"file": ("app.zip", io.BytesIO(b"PK"), "application/zip")}
    r = c.post("/api/apps/upload/zip", data={"app_name": "../x", "display_name": "X"}, files=files)
    assert r.status_code == 400

    _add_app("taken")
    files = {"file": ("app.zip", io.BytesIO(b"PK"), "application/zip")}
    r = c.post("/api/apps/upload/zip", data={"app_name": "taken", "display_name": "X"}, files=files)
    assert r.status_code == 409


def test_patch_validates_environment_and_entrypoint(client_no_lifespan, instance):
    c = client_no_lifespan
    app_id = _add_app(app_type=AppType.PERPETUAL, state=AppState.STOPPED)
    source = instance.apps_dir / "demo" / "app"
    source.mkdir(parents=True)
    (source / "main.py").write_text("x")
    (source / "worker.py").write_text("x")

    assert c.patch(f"/api/apps/{app_id}", json={"environment": {"1BAD": "x"}}).status_code == 422
    assert (
        c.patch(f"/api/apps/{app_id}", json={"entrypoint": "../../etc/passwd"}).status_code == 400
    )

    r = c.patch(
        f"/api/apps/{app_id}",
        json={"entrypoint": "worker.py", "environment": {"API_KEY": "s3cret"}},
    )
    assert r.status_code == 200
    assert r.json()["entrypoint"] == "worker.py"
    assert r.json()["environment"] == {"API_KEY": "s3cret"}
    assert c.get(f"/api/apps/{app_id}/files").json()["python_files"] == ["main.py", "worker.py"]


def test_full_add_flow_installs_schedules_and_activates(client_no_lifespan, instance, monkeypatch):
    """One request: upload → install → schedule → activate, reported as steps."""
    monkeypatch.setattr(
        "mantyx.core.venv_manager.VenvManager.install_requirements", lambda *a, **k: "ok"
    )
    monkeypatch.setattr("mantyx.core.venv_manager.VenvManager.ensure_healthy", lambda *a, **k: None)
    c = client_no_lifespan
    buf = io.BytesIO()
    with ZipFile(buf, "w") as zf:
        zf.writestr("Report/main.py", "print('hi')\n")
    buf.seek(0)

    r = c.post(
        "/api/apps/upload/zip",
        data={
            "app_name": "report",
            "display_name": "Daily report",
            "app_type": "SCHEDULED",
            "install": "true",
            "activate": "true",
            "schedule": json.dumps(
                {"name": "Mornings", "schedule_type": "cron", "cron_expression": "0 7 * * *"}
            ),
        },
        files={"file": ("Report.zip", buf, "application/zip")},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["task_id"]

    for _ in range(100):
        task = c.get(f"/api/apps/tasks/{task_id}").json()
        if task["status"] != "running":
            break
        time.sleep(0.05)
    assert task["status"] == "success", task
    assert [s["status"] for s in task["steps"]] == ["done", "done", "done", "done"]

    app = c.get(f"/api/apps/{task['result']['app_id']}").json()
    assert app["status"] == "scheduled"
    assert app["entrypoint"] == "main.py"  # found inside the zipped folder
    assert app["enabled_schedule_count"] == 1


# ── logs, retention, schema upgrades ────────────────────────────────────────


def test_log_chunks_tail_and_follow(tmp_path):
    log = tmp_path / "out.log"
    log.write_text("a" * 100)
    first = read_log_chunk(log, -1, max_bytes=10)
    assert first["output"] == "a" * 10 and first["truncated"] and first["offset"] == 100

    with log.open("a") as f:
        f.write("new line\n")
    nxt = read_log_chunk(log, first["offset"])
    assert nxt["output"] == "new line\n"

    log.write_text("rotated\n")  # file shrank
    after = read_log_chunk(log, nxt["offset"])
    assert after["reset"] and after["output"] == "rotated\n"


def test_retention_keeps_recent_runs_and_removes_old_ones(instance):
    from mantyx.core.maintenance import KEEP_RECENT_RUNS_PER_APP, run_retention

    app_id = _add_app()
    log_dir = instance.logs_dir / "demo"
    log_dir.mkdir(parents=True)
    old = datetime.now() - timedelta(days=instance.log_retention_days + 5)
    with get_db() as session:
        for i in range(KEEP_RECENT_RUNS_PER_APP + 5):
            path = log_dir / f"execution_{i}_stdout.log"
            path.write_text("x")
            session.add(
                Execution(
                    app_id=app_id,
                    status=ExecutionStatus.SUCCESS,
                    started_at=old,
                    stdout_path=str(path),
                )
            )
        session.add(LogEntry(app_id=app_id, source="t", message="old", timestamp=old))

    run_retention()

    with get_db() as session:
        assert session.query(Execution).count() == KEEP_RECENT_RUNS_PER_APP
        assert session.query(LogEntry).count() == 0
    assert len(list(log_dir.glob("*.log"))) == KEEP_RECENT_RUNS_PER_APP


def test_startup_adds_columns_missing_from_old_databases(tmp_path):
    base = tmp_path / "old"
    (base / "data").mkdir(parents=True)
    db = sqlite3.connect(base / "data" / "mantyx.db")
    # The apps table as created by the very first Mantyx release.
    db.execute(
        "CREATE TABLE apps (id INTEGER PRIMARY KEY, name VARCHAR(255) NOT NULL UNIQUE, "
        "display_name VARCHAR(255) NOT NULL, description TEXT, app_type VARCHAR(9) NOT NULL, "
        "state VARCHAR(9) NOT NULL, version VARCHAR(50), entrypoint VARCHAR(255) NOT NULL, "
        "config JSON, environment JSON, restart_policy VARCHAR(50), max_restarts INTEGER, "
        "restart_delay INTEGER, health_check_enabled BOOLEAN, health_check_url VARCHAR(255), "
        "health_check_interval INTEGER, web_url VARCHAR(255), web_port INTEGER, pid INTEGER, "
        "restart_count INTEGER, last_restart_at DATETIME, last_health_check DATETIME, "
        "health_status VARCHAR(50), last_error TEXT, last_error_at DATETIME, is_deleted BOOLEAN, "
        "deleted_at DATETIME, git_url VARCHAR(500), git_branch VARCHAR(100), git_commit VARCHAR(40), "
        "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    )
    db.execute(
        "INSERT INTO apps (name, display_name, app_type, state, entrypoint, web_port, is_deleted) "
        "VALUES ('legacy', 'Legacy', 'PERPETUAL', 'RUNNING', 'main.py', 8080, 0)"
    )
    db.commit()
    db.close()

    init_settings(base_dir=base, database_url=None)
    try:
        init_db()
        with get_db() as session:
            app = session.query(App).one()
            assert app.update_count == 0 or app.update_count is None
            assert app.web_port_source == "manual"
            assert app.state == AppState.RUNNING
        init_db()  # idempotent
    finally:
        database_module.dispose_engine()
        config_module._settings = None
