"""
Tests for ProcessSupervisor robustness fixes.

Covers:
  Fix 1 – silent DB failures in start_app() success path
  Fix 2 – orphaned PENDING execution records when cleanup query returns None
  Fix 3 – DetachedInstanceError in restart_app() (now accepts app_id: int)
  Fix 4 – nested-session race in monitor_apps() crash-recovery path
"""

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import psutil
import pytest

from mantyx.core.supervisor import ProcessSupervisor
from mantyx.models.app import App, AppState, AppType
from mantyx.models.execution import Execution, ExecutionStatus

# ── DB helpers ────────────────────────────────────────────────────────────────


def _real_get_db(session_factory):
    """Context-manager factory backed by the test sessionmaker."""

    @contextmanager
    def _get_db():
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _get_db


def _null_query_get_db(session_factory, null_models):
    """Like _real_get_db, but patches session.query to return None for listed models."""

    @contextmanager
    def _get_db():
        session = session_factory()
        original_query = session.query

        def _query(model, *args, **kwargs):
            if model in null_models:
                mock_q = MagicMock()
                mock_q.filter.return_value.first.return_value = None
                return mock_q
            return original_query(model, *args, **kwargs)

        session.query = _query
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _get_db


def _sequenced_get_db(session_factory, null_on_call, null_models):
    """Uses the real DB for all calls except call #null_on_call, where null_models return None."""
    real = _real_get_db(session_factory)
    null = _null_query_get_db(session_factory, null_models)
    call_count = [0]

    def _get_db():
        call_count[0] += 1
        return (null if call_count[0] == null_on_call else real)()

    return _get_db


def _make_app(
    session_factory,
    *,
    state=AppState.ENABLED,
    pid=None,
    restart_policy="on-failure",
    max_restarts=3,
    restart_count=0,
):
    """Insert a minimal test App row and return its id."""
    session = session_factory()
    app = App(
        name="testapp",
        display_name="Test App",
        app_type=AppType.PERPETUAL,
        state=state,
        entrypoint="main.py",
        pid=pid,
        restart_policy=restart_policy,
        max_restarts=max_restarts,
        restart_count=restart_count,
    )
    session.add(app)
    session.commit()
    app_id = app.id
    session.close()
    return app_id


def _query_app(session_factory, app_id):
    """Re-fetch an App row in a fresh session."""
    session = session_factory()
    app = session.query(App).filter(App.id == app_id).first()
    session.close()
    return app


def _query_execution(session_factory, app_id):
    """Re-fetch the first Execution row for the given app_id."""
    session = session_factory()
    exc = session.query(Execution).filter(Execution.app_id == app_id).first()
    session.close()
    return exc


# ── supervisor fixture ────────────────────────────────────────────────────────


@pytest.fixture
def supervisor_env(test_db, tmp_path):
    """
    Patches all ProcessSupervisor external dependencies.

    Yields a dict with:
      test_db  – sessionmaker pointing at the SQLite test DB
      process  – the mock subprocess.Popen return value (pid=12345)
      popen    – the mock Popen callable (set side_effect to simulate failures)
    """
    app_dir = tmp_path / "testapp" / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "main.py").touch()

    mock_python = tmp_path / "python"
    mock_python.touch()

    mock_proc = MagicMock()
    mock_proc.pid = 12345

    log_stdout = tmp_path / "stdout.log"
    log_stderr = tmp_path / "stderr.log"

    mock_settings = MagicMock()
    mock_settings.apps_dir = tmp_path
    mock_settings.restart_window = 300

    with (
        patch("mantyx.core.supervisor.get_db", _real_get_db(test_db)),
        patch("mantyx.core.supervisor.get_settings", return_value=mock_settings),
        patch("mantyx.core.supervisor.VenvManager") as MockVenvManager,
        patch("subprocess.Popen", return_value=mock_proc) as mock_popen,
        patch("mantyx.core.supervisor.get_app_log_path", return_value=(log_stdout, log_stderr)),
    ):
        venv_inst = MagicMock()
        venv_inst.get_python_executable.return_value = mock_python
        MockVenvManager.return_value = venv_inst

        yield {"test_db": test_db, "process": mock_proc, "popen": mock_popen}


# ── Fix 1: start_app() success path – DB record missing ──────────────────────


def test_start_app_success_updates_db_and_returns_running_execution(supervisor_env):
    """Happy path: DB rows are updated and the returned Execution has RUNNING state."""
    env = supervisor_env
    app_id = _make_app(env["test_db"])

    execution = ProcessSupervisor().start_app(app_id)

    assert execution.status == ExecutionStatus.RUNNING
    assert execution.pid == 12345

    db_app = _query_app(env["test_db"], app_id)
    assert db_app.state == AppState.RUNNING
    assert db_app.pid == 12345

    db_exec = _query_execution(env["test_db"], app_id)
    assert db_exec.status == ExecutionStatus.RUNNING
    assert db_exec.pid == 12345


def test_start_app_logs_error_when_exec_record_missing(supervisor_env):
    """
    If the Execution row can't be found after Popen succeeds, an error is logged.
    The returned Execution must still carry RUNNING state (in-memory patch from Fix 1).
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(test_db)

    # Call 3 is the "update after success" session — make Execution query return None there.
    get_db_seq = _sequenced_get_db(test_db, null_on_call=3, null_models={Execution})

    with patch("mantyx.core.supervisor.get_db", get_db_seq):
        with patch("mantyx.core.supervisor.logger") as mock_logger:
            execution = ProcessSupervisor().start_app(app_id)

    # Caller still sees accurate state even though the DB record wasn't found.
    assert execution.status == ExecutionStatus.RUNNING
    assert execution.pid == 12345

    error_messages = [c.args[0] for c in mock_logger.error.call_args_list]
    assert any("not found after starting" in m for m in error_messages)


def test_start_app_logs_error_when_app_record_missing(supervisor_env):
    """
    If the App row can't be found in the post-Popen update session, an error is logged.
    The Execution is still updated and returned with RUNNING state.
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(test_db)

    get_db_seq = _sequenced_get_db(test_db, null_on_call=3, null_models={App})

    with patch("mantyx.core.supervisor.get_db", get_db_seq):
        with patch("mantyx.core.supervisor.logger") as mock_logger:
            execution = ProcessSupervisor().start_app(app_id)

    assert execution.status == ExecutionStatus.RUNNING

    error_messages = [c.args[0] for c in mock_logger.error.call_args_list]
    assert any("not found after process start" in m for m in error_messages)


# ── Fix 2: start_app() failure path – orphaned PENDING records ───────────────


def test_start_app_popen_fails_marks_execution_and_app_failed(supervisor_env):
    """When Popen raises, both the Execution and App are marked FAILED in the DB."""
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(test_db)

    env["popen"].side_effect = OSError("permission denied")

    with pytest.raises(OSError):
        ProcessSupervisor().start_app(app_id)

    db_app = _query_app(test_db, app_id)
    assert db_app.state == AppState.FAILED
    assert "permission denied" in db_app.last_error

    db_exec = _query_execution(test_db, app_id)
    assert db_exec.status == ExecutionStatus.FAILED
    assert "permission denied" in db_exec.error_message


def test_start_app_logs_warning_when_exec_record_missing_on_failure(supervisor_env):
    """
    If the Execution row can't be found during failure cleanup, a warning is logged
    so the operator knows the record may be stuck in PENDING.
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(test_db)

    env["popen"].side_effect = OSError("boom")

    # When Popen raises, the error handler is the 3rd get_db call.
    get_db_seq = _sequenced_get_db(test_db, null_on_call=3, null_models={Execution})

    with patch("mantyx.core.supervisor.get_db", get_db_seq):
        with patch("mantyx.core.supervisor.logger") as mock_logger:
            with pytest.raises(OSError):
                ProcessSupervisor().start_app(app_id)

    warning_messages = [c.args[0] for c in mock_logger.warning.call_args_list]
    assert any("remain in PENDING state" in m for m in warning_messages)


# ── Fix 3: restart_app() takes app_id: int ───────────────────────────────────


def test_restart_app_not_found_raises(supervisor_env):
    """restart_app() raises RuntimeError for an app_id that doesn't exist in the DB."""
    with pytest.raises(RuntimeError, match="not found"):
        ProcessSupervisor().restart_app(99999)


def test_restart_app_calls_stop_when_app_is_running(supervisor_env):
    """restart_app() calls stop_app() with a fresh App while the session is still open."""
    env = supervisor_env
    app_id = _make_app(env["test_db"], state=AppState.RUNNING, pid=99999)

    captured_ids: list[int] = []

    def _capture(app, **_kwargs):
        # Access app.id now, while restart_app's session is still live.
        # Accessing it after the with-block exits would raise DetachedInstanceError.
        captured_ids.append(app.id)

    supervisor = ProcessSupervisor()
    with patch.object(supervisor, "stop_app", side_effect=_capture):
        with patch.object(supervisor, "start_app", return_value=MagicMock()):
            supervisor.restart_app(app_id)

    assert captured_ids == [app_id]


def test_restart_app_skips_stop_when_not_running(supervisor_env):
    """restart_app() does NOT call stop_app() when the app is not in RUNNING state."""
    env = supervisor_env
    app_id = _make_app(env["test_db"], state=AppState.ENABLED)

    supervisor = ProcessSupervisor()
    with patch.object(supervisor, "stop_app") as mock_stop:
        with patch.object(supervisor, "start_app", return_value=MagicMock()):
            supervisor.restart_app(app_id)

    mock_stop.assert_not_called()


def test_restart_app_increments_restart_count(supervisor_env):
    """restart_app() increments the restart_count in the DB."""
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(test_db, state=AppState.ENABLED, restart_count=2)

    supervisor = ProcessSupervisor()
    with patch.object(supervisor, "stop_app"):
        with patch.object(supervisor, "start_app", return_value=MagicMock()):
            supervisor.restart_app(app_id)

    db_app = _query_app(test_db, app_id)
    assert db_app.restart_count == 3


# ── Fix 4: monitor_apps() – no nested-session race ───────────────────────────


def test_monitor_apps_exceeded_restarts_marks_app_failed(supervisor_env):
    """
    When a crashed app has exhausted its restart budget, monitor_apps() marks it
    FAILED immediately (inside the reading session, before any restart attempt).
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(
        test_db,
        state=AppState.RUNNING,
        pid=99999,
        restart_policy="on-failure",
        max_restarts=3,
        restart_count=3,
    )

    with patch("psutil.Process", side_effect=psutil.NoSuchProcess(99999)):
        ProcessSupervisor().monitor_apps()

    db_app = _query_app(test_db, app_id)
    assert db_app.state == AppState.FAILED
    assert db_app.last_error == "Exceeded maximum restart attempts"


def test_monitor_apps_restart_called_with_int_app_id(supervisor_env):
    """
    After the outer reading session closes, restart_app() is called with the
    integer app_id — never with a potentially-detached ORM App object.
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(
        test_db,
        state=AppState.RUNNING,
        pid=99999,
        restart_policy="always",
    )

    supervisor = ProcessSupervisor()
    with (
        patch("psutil.Process", side_effect=psutil.NoSuchProcess(99999)),
        patch.object(supervisor, "restart_app") as mock_restart,
    ):
        supervisor.monitor_apps()

    mock_restart.assert_called_once_with(app_id)


def test_monitor_apps_restart_failure_marks_app_failed_via_fresh_session(supervisor_env):
    """
    When restart_app() raises, monitor_apps() marks the app FAILED using a new session
    opened after the outer reading session has already committed and closed.
    """
    env = supervisor_env
    test_db = env["test_db"]
    app_id = _make_app(
        test_db,
        state=AppState.RUNNING,
        pid=99999,
        restart_policy="always",
    )

    supervisor = ProcessSupervisor()
    with (
        patch("psutil.Process", side_effect=psutil.NoSuchProcess(99999)),
        patch.object(supervisor, "restart_app", side_effect=RuntimeError("start failed")),
    ):
        supervisor.monitor_apps()

    db_app = _query_app(test_db, app_id)
    assert db_app.state == AppState.FAILED
    assert "start failed" in db_app.last_error
