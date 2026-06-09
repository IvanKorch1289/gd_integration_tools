"""Tests for src.backend.dsl.di.decorators (Sprint 40 W1).

# ruff: noqa: S101
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.di.container import Container
from src.backend.dsl.di.decorators import inject
from src.backend.dsl.di.types import InjectMarker


@pytest.fixture(autouse=True)
def _reset_container_state() -> None:
    """Сбрасывает _type_map перед каждым тестом."""
    Container._type_map.clear()
    yield
    Container._type_map.clear()


# ── basic injection ──


def test_inject_injects_exchange_and_context() -> None:
    @inject
    def handler(exchange: Any, context: Any) -> tuple[Any, Any]:
        return (exchange, context)

    result = handler(exchange="ex", context="ctx")
    assert result == ("ex", "ctx")


def test_inject_injects_container_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_resolve = MagicMock(return_value="resolved_svc")
    monkeypatch.setattr(Container, "resolve", fake_resolve)

    @inject
    def handler(exchange: Any, svc: str = Container.depends(key="my.svc")) -> str:
        return svc

    result = handler(exchange="ex")
    assert result == "resolved_svc"
    fake_resolve.assert_called_once()
    marker = fake_resolve.call_args[0][0]
    assert isinstance(marker, InjectMarker)
    assert marker.key == "my.svc"


# ── async support ──


@pytest.mark.asyncio
async def test_inject_async_handler() -> None:
    @inject
    async def async_handler(exchange: Any, value: int = 42) -> int:
        return value

    result = await async_handler(exchange="ex")
    assert result == 42


# ── __inject_markers__ flag ──


def test_inject_sets_flag() -> None:
    @inject
    def handler(exchange: Any) -> None:
        pass

    assert getattr(handler, "__inject_markers__", False) is True


# ── passthrough kwargs ──


def test_inject_passthrough_existing_kwargs() -> None:
    @inject
    def handler(exchange: Any, extra: str = "default") -> str:
        return extra

    assert handler(exchange="ex", extra="override") == "override"
