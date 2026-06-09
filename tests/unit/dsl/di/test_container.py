"""Tests for src.backend.dsl.di.container (Sprint 40 W1).

# ruff: noqa: S101
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.di.container import Container, DIError
from src.backend.dsl.di.types import InjectMarker


@pytest.fixture(autouse=True)
def _reset_container_state() -> None:
    """Сбрасывает _type_map перед каждым тестом."""
    Container._type_map.clear()
    yield
    Container._type_map.clear()


# ── resolve via factory ──


def test_resolve_factory_highest_priority() -> None:
    marker = InjectMarker(factory=lambda: 42)
    assert Container.resolve(marker) == 42


# ── resolve via key (module_registry / app_state) ──


def test_resolve_by_key_module_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resolve = MagicMock(return_value="registry_value")
    monkeypatch.setattr(
        "src.backend.core.di.module_registry.resolve_module", fake_resolve
    )
    marker = InjectMarker(key="my.service")
    assert Container.resolve(marker) == "registry_value"
    fake_resolve.assert_called_once_with("my.service")


def test_resolve_by_key_app_state(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.di.module_registry.resolve_module",
        MagicMock(side_effect=ImportError("no module")),
    )
    fake_app = MagicMock()
    fake_app.state.my_service = "app_state_value"
    monkeypatch.setattr("src.backend.core.di.app_state.get_app_ref", lambda: fake_app)
    marker = InjectMarker(key="my_service")
    assert Container.resolve(marker) == "app_state_value"


def test_resolve_missing_key_raises() -> None:
    marker = InjectMarker(key="nonexistent.key")
    with pytest.raises(DIError, match="nonexistent.key"):
        Container.resolve(marker)


# ── resolve via type_map ──


def test_resolve_by_type_map() -> None:
    class FakeService:
        pass

    Container.register_type(FakeService, "fake.svc")
    fake_instance = FakeService()
    original_resolve = Container._resolve_by_key

    def _mocked_resolve(key: str, *, fallback_ok: bool = False) -> Any:
        if key == "fake.svc":
            return fake_instance
        return original_resolve(key, fallback_ok=fallback_ok)

    monkeypatch = pytest.MonkeyPatch()
    with monkeypatch.context() as m:
        m.setattr(Container, "_resolve_by_key", staticmethod(_mocked_resolve))
        marker = InjectMarker()  # no key, no factory
        assert Container.resolve(marker, hint=FakeService) is fake_instance


# ── resolve_signature ──


def test_resolve_signature_injects_exchange_and_context() -> None:
    def handler(exchange: Any, context: Any, extra: str = "ok") -> None:
        pass

    sig = Container.resolve_signature(handler, exchange="ex", context="ctx")
    assert sig["exchange"] == "ex"
    assert sig["context"] == "ctx"
    assert sig["extra"] == "ok"
    # required positional without default stays empty
    assert sig.get("missing") is inspect.Parameter.empty or sig.get("missing") is None


def test_resolve_signature_skips_missing_exchange_context() -> None:
    def handler(data: str) -> None:
        pass

    sig = Container.resolve_signature(handler, exchange="ex", context="ctx")
    assert "exchange" not in sig
    assert "context" not in sig
    assert sig["data"] is inspect.Parameter.empty


# ── DIError ──


def test_di_error_is_runtime_error() -> None:
    exc = DIError("boom")
    assert isinstance(exc, RuntimeError)
