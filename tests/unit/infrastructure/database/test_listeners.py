"""Unit-tests for DatabaseListener."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.database.listeners import DatabaseListener


@pytest.fixture
def mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.sync_engine = MagicMock()
    return engine


def test_listener_registers_handlers(mock_engine: MagicMock) -> None:
    with patch("src.backend.infrastructure.database.listeners.event.listens_for") as mock_listen:
        DatabaseListener(mock_engine, "test_db", 0.5)
        assert mock_listen.call_count == 3


def test_before_cursor_execute_sets_start_time() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.listeners.event.listens_for", fake_listens_for):
        DatabaseListener(MagicMock(sync_engine=MagicMock()), "db", 0.5)

    context = SimpleNamespace()
    captured["before_cursor_execute"](None, None, "SELECT 1", (), context, False)
    assert hasattr(context, "_query_start_time")


def test_after_cursor_execute_logs_slow_query() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.listeners.event.listens_for", fake_listens_for):
        listener = DatabaseListener(MagicMock(sync_engine=MagicMock()), "db", 0.1)

    context = SimpleNamespace(_query_start_time=0.0)
    # after_cursor_execute calls monotonic() ONCE (only at line 59 duration calc);
    # before_cursor_execute is not invoked in this test (start time pre-set in context).
    with patch(
        "src.backend.infrastructure.database.listeners.monotonic", return_value=1.0
    ):
        with patch.object(listener.logger, "warning") as mock_warning:
            captured["after_cursor_execute"](None, None, "SELECT 1", (), context, False)
    mock_warning.assert_called_once()
    assert "Slow SQL query detected" in mock_warning.call_args[0][0]


def test_after_cursor_execute_logs_debug() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.listeners.event.listens_for", fake_listens_for):
        listener = DatabaseListener(MagicMock(sync_engine=MagicMock()), "db", 10.0)

    context = SimpleNamespace(_query_start_time=0.0)
    with patch(
        "src.backend.infrastructure.database.listeners.monotonic", return_value=0.01
    ):
        with patch.object(listener.logger, "debug") as mock_debug:
            captured["after_cursor_execute"](None, None, "SELECT 1", (), context, False)
    mock_debug.assert_called_once()
    assert "SQL query executed" in mock_debug.call_args[0][0]


def test_handle_error_logs_exception() -> None:
    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.listeners.event.listens_for", fake_listens_for):
        listener = DatabaseListener(MagicMock(sync_engine=MagicMock()), "db", 1.0)

    exc_ctx = SimpleNamespace(
        is_disconnect=True,
        statement="SELECT * FROM users",
        original_exception=RuntimeError("boom"),
    )
    with patch.object(listener.logger, "error") as mock_error:
        captured["handle_error"](exc_ctx)
    mock_error.assert_called_once()
    assert "Database driver error" in mock_error.call_args[0][0]
