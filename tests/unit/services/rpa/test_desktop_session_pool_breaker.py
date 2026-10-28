"""ADR-0368 — Circuit Breaker desktop-RPA pool должен реально открываться.

До фикса ``breaker_guard.__aexit__(None, None, None)`` терял исключение →
purgatory видел «успешный» запрос → failure-counter сбрасывался, breaker
оставался ``closed`` (7 ConnectError подряд — state closed).

ВАЖНО: ``get_breaker_registry()`` — синглтон, состояние сбрасывается
в autouse-фикстуре.
"""

from __future__ import annotations

from unittest.mock import patch

import httpx
import pytest

from src.backend.core.resilience.breaker import CircuitOpen, get_breaker_registry
from src.backend.services.rpa.desktop_session_pool import DesktopRPASessionPool


@pytest.fixture(autouse=True)
def _reset_breaker_registry() -> None:
    """Сброс синглона breaker'ов (иначе состояние протекает между тестами)."""
    get_breaker_registry().reset()
    yield
    get_breaker_registry().reset()


@pytest.fixture
def pool() -> DesktopRPASessionPool:
    return DesktopRPASessionPool(
        base_url="http://rpa-test:8080", timeout=1.0, ttl_seconds=60.0, max_sessions=4
    )


@pytest.mark.unit
class TestDesktopPoolCircuitBreaker:
    """Breaker пула desktop-RPA: учёт отказов и fail-fast при open."""

    async def test_breaker_opens_after_repeated_connect_errors(
        self, pool: DesktopRPASessionPool
    ) -> None:
        with patch("src.backend.services.rpa.desktop_session_pool.make_http_client"):
            for _ in range(5):
                with pytest.raises(httpx.ConnectError):
                    async with pool.acquire("notepad"):
                        raise httpx.ConnectError("stale handle")

        breaker = get_breaker_registry().get("desktop_rpa_pool")
        assert breaker is not None
        assert breaker.state == "open", (
            f"breaker не открылся после 5 отказов (state={breaker.state})"
        )

    async def test_acquire_raises_circuit_open_when_breaker_is_open(
        self, pool: DesktopRPASessionPool
    ) -> None:
        with patch("src.backend.services.rpa.desktop_session_pool.make_http_client"):
            for _ in range(5):
                with pytest.raises(httpx.ConnectError):
                    async with pool.acquire("notepad"):
                        raise httpx.ConnectError("stale handle")

            with pytest.raises(CircuitOpen):
                async with pool.acquire("notepad"):
                    pass  # pragma: no cover — до breaker'а сюда не дойти
