"""
Tests for the /apps/{id}/run API endpoint.

Covers Fix 5 – silent thread failures: if execute_scheduled_app raises, the
exception must be logged at ERROR level rather than silently discarded.
"""

import time
from unittest.mock import MagicMock, patch

from mantyx.api.apps import run_scheduled_app
from mantyx.models.app import AppState, AppType


def _mock_db_with_app(app_type=AppType.SCHEDULED, state=AppState.ENABLED, name="testapp"):
    """Return a mock SQLAlchemy session whose query chain yields a configured mock App."""
    mock_app = MagicMock()
    mock_app.app_type = app_type
    mock_app.state = state
    mock_app.name = name

    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = mock_app
    return mock_db, mock_app


# ── Fix 5: silent thread failures ────────────────────────────────────────────


def test_run_endpoint_logs_error_when_thread_raises():
    """
    If execute_scheduled_app raises inside the background thread, the exception
    must be logged at ERROR level (not silently swallowed).
    The HTTP response should still report "App execution started".
    """
    mock_db, _ = _mock_db_with_app()

    with (
        patch("mantyx.core.scheduler.execute_scheduled_app", side_effect=RuntimeError("kaboom")),
        patch("mantyx.api.apps.logger") as mock_logger,
    ):
        result = run_scheduled_app(app_id=1, db=mock_db)
        # Give the background thread enough time to run and hit the exception.
        time.sleep(0.2)

    assert result == {"message": "App execution started"}

    mock_logger.error.assert_called_once()
    logged_message = mock_logger.error.call_args.args[0]
    assert "kaboom" in logged_message
    assert "testapp" in logged_message


def test_run_endpoint_returns_immediately_without_waiting_for_thread():
    """
    The endpoint must return before execute_scheduled_app finishes so it doesn't
    block the request. We verify it returns while the "app" is still running.
    """
    import threading

    started = threading.Event()
    finished = threading.Event()

    def slow_execution(app_id, schedule_id):
        started.set()
        time.sleep(5)  # Would block if called synchronously
        finished.set()

    mock_db, _ = _mock_db_with_app()

    with patch("mantyx.core.scheduler.execute_scheduled_app", side_effect=slow_execution):
        result = run_scheduled_app(app_id=1, db=mock_db)

    # The route returned immediately; the slow function hasn't finished yet.
    assert result == {"message": "App execution started"}
    assert started.wait(timeout=1), "Thread never started"
    assert not finished.is_set(), "Thread finished synchronously (endpoint blocked)"
