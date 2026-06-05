"""Unit-tests for RLS tenant listener."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.database.rls_listener import (
    install_rls_tenant_listener,
    _INSTALLED_ENGINES,
)


@pytest.fixture(autouse=True)
def _reset_installed() -> None:
    _INSTALLED_ENGINES.clear()


@pytest.fixture
def mock_engine() -> MagicMock:
    engine = MagicMock()
    engine.sync_engine = MagicMock()
    engine.sync_engine.dialect.name = "postgresql"
    return engine


def test_install_skips_when_feature_disabled(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=False),
    )
    install_rls_tenant_listener(mock_engine)
    assert len(_INSTALLED_ENGINES) == 0


def test_install_skips_for_non_pg(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=True),
    )
    mock_engine.sync_engine.dialect.name = "sqlite"
    install_rls_tenant_listener(mock_engine)
    assert len(_INSTALLED_ENGINES) == 0


def test_install_idempotent(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=True),
    )
    install_rls_tenant_listener(mock_engine)
    install_rls_tenant_listener(mock_engine)
    assert len(_INSTALLED_ENGINES) == 1


def test_after_begin_sets_tenant(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=True),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.current_tenant",
        lambda: SimpleNamespace(tenant_id="bank_a"),
    )

    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.rls_listener.event.listens_for", fake_listens_for):
        install_rls_tenant_listener(mock_engine)

    connection = MagicMock()
    connection.dialect.name = "postgresql"
    captured["after_begin"](None, None, connection)
    connection.exec_driver_sql.assert_called_once()
    args = connection.exec_driver_sql.call_args[0]
    assert "set_config" in args[0]
    assert args[1] == ("bank_a",)


def test_after_begin_skips_no_tenant(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=True),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.current_tenant",
        lambda: None,
    )

    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.rls_listener.event.listens_for", fake_listens_for):
        install_rls_tenant_listener(mock_engine)

    connection = MagicMock()
    connection.dialect.name = "postgresql"
    captured["after_begin"](None, None, connection)
    connection.exec_driver_sql.assert_not_called()


def test_after_begin_logs_error(mock_engine: MagicMock, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.feature_flags",
        MagicMock(rls_postgres_enforce=True),
    )
    monkeypatch.setattr(
        "src.backend.infrastructure.database.rls_listener.current_tenant",
        lambda: SimpleNamespace(tenant_id="bank_a"),
    )

    captured = {}

    def fake_listens_for(target, identifier):
        def decorator(fn):
            captured[identifier] = fn
            return fn
        return decorator

    with patch("src.backend.infrastructure.database.rls_listener.event.listens_for", fake_listens_for):
        install_rls_tenant_listener(mock_engine)

    connection = MagicMock()
    connection.dialect.name = "postgresql"
    connection.exec_driver_sql = MagicMock(side_effect=RuntimeError("pg down"))
    with caplog.at_level("WARNING"):
        captured["after_begin"](None, None, connection)
    assert "RLS SET LOCAL" in caplog.text
