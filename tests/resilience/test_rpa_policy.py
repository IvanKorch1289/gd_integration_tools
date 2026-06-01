"""Sprint 21 W3 — RPACallPolicy resilience tests.

Источник: PLAN.md V22.2 §4 + ADR-NEW-13 + B-02 closure.

Сценарии (5 transport-failure без toxiproxy через synthetic exceptions):
    1. network partition (httpx.ConnectError) — retry до exhausted → DLQ.
    2. slow response (asyncio timeout simulation) — retry-loop honors backoff.
    3. connection refused (ConnectionRefusedError) — retry до exhausted.
    4. TLS handshake fail (ssl.SSLError) — retry до exhausted.
    5. HTTP 5xx burst (custom UpstreamError на N attempts → success на N+1).

Bonus: feature-flag OFF — call() в passthrough режиме (без retry).
"""

from __future__ import annotations

import asyncio
import ssl
from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason, DLQWriter
from src.backend.core.resilience.rpa_policy import (
    RPACallExhausted,
    RPACallPolicy,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _enable_rpa_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    """Включает feature-flag для тестов."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags,
        "rpa_resilience_wrapper_enabled",
        True,
        raising=False,
    )


class _InMemoryDLQ:
    """Простой DLQWriter для assertions."""

    def __init__(self) -> None:
        self.envelopes: list[DLQEnvelope] = []

    async def write(self, envelope: DLQEnvelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture
def dlq() -> _InMemoryDLQ:
    return _InMemoryDLQ()


def _make_policy(
    dlq: DLQWriter | None,
    *,
    max_attempts: int = 3,
    backoff: float = 0.001,
) -> RPACallPolicy:
    return RPACallPolicy(
        name="test",
        max_attempts=max_attempts,
        backoff_initial_seconds=backoff,
        backoff_max_seconds=backoff * 10,
        jitter=0.0,
        dlq_writer=dlq,
    )


async def test_network_partition_exhausts_and_dlq(dlq: _InMemoryDLQ) -> None:
    """Scenario 1: ConnectError repeats N times → RPACallExhausted + DLQ."""
    policy = _make_policy(dlq)
    coro = AsyncMock(side_effect=httpx.ConnectError("network down"))
    with pytest.raises(RPACallExhausted):
        await policy.call(coro, transport="cdc", payload={"event": "x"})
    assert coro.await_count == 3
    assert len(dlq.envelopes) == 1
    env = dlq.envelopes[0]
    assert env.transport == "cdc"
    assert env.reason == DLQReason.RETRIES_EXHAUSTED
    assert env.error_class == "ConnectError"
    assert env.retry_count == 3


async def test_slow_response_backoff_applied(dlq: _InMemoryDLQ) -> None:
    """Scenario 2: TimeoutError → retry с backoff (синхронный замер интервала)."""
    policy = RPACallPolicy(
        name="slow",
        max_attempts=3,
        backoff_initial_seconds=0.02,
        backoff_max_seconds=0.1,
        jitter=0.0,
        dlq_writer=dlq,
    )
    coro = AsyncMock(side_effect=asyncio.TimeoutError("slow"))
    start = asyncio.get_event_loop().time()
    with pytest.raises(RPACallExhausted):
        await policy.call(coro, transport="file_watcher")
    elapsed = asyncio.get_event_loop().time() - start
    # backoff(0)=0.02 + backoff(1)=0.04 = 0.06 (хотя последний sleep после
    # последней попытки НЕ выполняется → ожидаем ~0.06s)
    assert elapsed >= 0.04, f"backoff не применён: elapsed={elapsed}"
    assert coro.await_count == 3
    assert len(dlq.envelopes) == 1


async def test_connection_refused_exhausts(dlq: _InMemoryDLQ) -> None:
    """Scenario 3: ConnectionRefusedError exhausts."""
    policy = _make_policy(dlq)
    coro = AsyncMock(side_effect=ConnectionRefusedError("refused"))
    with pytest.raises(RPACallExhausted):
        await policy.call(coro, transport="webhook")
    assert len(dlq.envelopes) == 1
    assert dlq.envelopes[0].transport == "webhook"


async def test_tls_handshake_fail_exhausts(dlq: _InMemoryDLQ) -> None:
    """Scenario 4: ssl.SSLError repeats → DLQ."""
    policy = _make_policy(dlq)
    coro = AsyncMock(side_effect=ssl.SSLError("handshake fail"))
    with pytest.raises(RPACallExhausted):
        await policy.call(coro, transport="desktop_rpa")
    assert dlq.envelopes[0].error_class == "SSLError"


async def test_http_5xx_burst_recovers(dlq: _InMemoryDLQ) -> None:
    """Scenario 5: 5xx-burst на первых N попытках → success на N+1."""

    class UpstreamError(Exception):
        pass

    policy = _make_policy(dlq)

    attempt_count = {"i": 0}

    async def _coro() -> str:
        attempt_count["i"] += 1
        if attempt_count["i"] < 3:
            raise UpstreamError(f"5xx burst attempt={attempt_count['i']}")
        return "ok"

    result = await policy.call(_coro, transport="browser_pool")
    assert result == "ok"
    assert attempt_count["i"] == 3
    assert dlq.envelopes == []  # DLQ пустой — success на 3-й


async def test_feature_flag_off_passes_through(
    dlq: _InMemoryDLQ, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Bonus: при выключенном feature-flag — coro вызывается без обёртки."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags,
        "rpa_resilience_wrapper_enabled",
        False,
        raising=False,
    )
    policy = _make_policy(dlq)
    coro = AsyncMock(side_effect=httpx.ConnectError("net down"))
    with pytest.raises(httpx.ConnectError):
        await policy.call(coro, transport="cdc")
    # При выключенном flag — только 1 вызов и DLQ пустой
    assert coro.await_count == 1
    assert dlq.envelopes == []


async def test_breaker_open_skips_call(dlq: _InMemoryDLQ) -> None:
    """Когда CB открыт — call() не вызывает coro и поднимает RPACallExhausted."""
    from src.backend.core.resilience.rpa_policy import _BreakerLike

    breaker = _BreakerLike(is_open=lambda: True)
    policy = RPACallPolicy(
        name="cb_test",
        max_attempts=3,
        backoff_initial_seconds=0.001,
        jitter=0.0,
        dlq_writer=dlq,
        breaker=breaker,
    )
    coro = AsyncMock()
    with pytest.raises(RPACallExhausted):
        await policy.call(coro, transport="webhook")
    coro.assert_not_awaited()


async def test_on_attempt_callback_invoked(dlq: _InMemoryDLQ) -> None:
    """on_attempt-hook вызывается на каждый attempt (success+failure)."""
    events: list[tuple[int, str | None]] = []

    def _hook(ctx: Any, attempt: int, err: BaseException | None) -> None:
        events.append((attempt, type(err).__name__ if err else None))

    attempt_count = {"i": 0}

    async def _coro() -> str:
        attempt_count["i"] += 1
        if attempt_count["i"] < 2:
            raise httpx.ConnectError("transient")
        return "ok"

    policy = RPACallPolicy(
        name="hook",
        max_attempts=3,
        backoff_initial_seconds=0.001,
        jitter=0.0,
        dlq_writer=dlq,
        on_attempt=_hook,
    )
    result = await policy.call(_coro, transport="browser_pool")
    assert result == "ok"
    assert events == [(0, "ConnectError"), (1, None)]
