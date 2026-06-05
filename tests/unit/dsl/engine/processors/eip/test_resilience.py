"""Unit-тесты resilience processors: DeadLetter, FallbackChain,
CircuitBreaker, Timeout.

Паттерн: async tests, _ex fixture, моки для redis / breaker registry.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.resilience import (
    CircuitBreakerProcessor,
    DeadLetterProcessor,
    FallbackChainProcessor,
    TimeoutProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class DummyProcessor(BaseProcessor):
    def __init__(self, payload: Any, name: str | None = None) -> None:
        super().__init__(name=name or "dummy")
        self._payload = payload

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.out_message = Message(body=self._payload)


class FailingProcessor(BaseProcessor):
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        raise RuntimeError("intentional fail")


class SetFailProcessor(BaseProcessor):
    def __init__(self, error: str = "fail", name: str | None = None) -> None:
        super().__init__(name=name or "set_fail")
        self._error = error

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.fail(self._error)


# =============================================================================
# DeadLetterProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_dead_letter_no_dlq_on_success() -> None:
    """При успешном sub-pipeline DLQ не вызывается."""
    dummy = DummyProcessor("ok")
    proc = DeadLetterProcessor(processors=[dummy])
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        await proc.process(e, ctx)

    assert e.status != ExchangeStatus.failed
    mock_redis.add_to_stream.assert_not_called()


@pytest.mark.asyncio
async def test_dead_letter_sends_to_dlq_on_failure() -> None:
    """При failed sub-pipeline exchange отправляется в DLQ."""
    failing = SetFailProcessor("boom")
    proc = DeadLetterProcessor(processors=[failing], dlq_stream="my-dlq")
    ctx = AsyncMock()
    e = _ex(body={"id": 1})

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    mock_redis.add_to_stream.assert_called_once()
    args = mock_redis.add_to_stream.call_args
    assert args.kwargs["stream_name"] == "my-dlq"


@pytest.mark.asyncio
async def test_dead_letter_dlq_error_logged() -> None:
    """Ошибка при отправке в DLQ логируется, не поднимается наружу."""
    failing = SetFailProcessor("boom")
    proc = DeadLetterProcessor(processors=[failing])
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client"
    ) as mock_redis:
        mock_redis.add_to_stream.side_effect = RuntimeError("redis down")
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed


@pytest.mark.asyncio
async def test_dead_letter_max_retries_zero() -> None:
    """max_retries=0 означает no retry logic inside processor."""
    failing = SetFailProcessor("boom")
    proc = DeadLetterProcessor(processors=[failing], max_retries=0)
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch("src.backend.infrastructure.clients.storage.redis.redis_client"):
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed


# =============================================================================
# FallbackChainProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_fallback_chain_first_success() -> None:
    """Первый процессор успешен — используется он."""
    ok = DummyProcessor("ok")
    proc = FallbackChainProcessor(processors=[ok])
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)
    assert e.out_message.body == "ok"
    assert e.properties.get("fallback_used") == 0


@pytest.mark.asyncio
async def test_fallback_chain_second_on_first_fail() -> None:
    """Первый падает, второй успешен."""
    fail = FailingProcessor()
    ok = DummyProcessor("ok")
    proc = FallbackChainProcessor(processors=[fail, ok])
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)
    assert e.out_message.body == "ok"
    assert e.properties.get("fallback_used") == 1


@pytest.mark.asyncio
async def test_fallback_chain_all_fail() -> None:
    """Все процессоры падают — exchange.fail."""
    fail1 = FailingProcessor()
    fail2 = FailingProcessor()
    proc = FallbackChainProcessor(processors=[fail1, fail2])
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)
    assert e.status == ExchangeStatus.failed
    assert "All fallbacks exhausted" in (e.error or "")


@pytest.mark.asyncio
async def test_fallback_chain_exchange_fail_status() -> None:
    """Процессор выставляет failed статус, но не raise — fallback продолжается."""
    set_fail = SetFailProcessor("err")
    ok = DummyProcessor("ok")
    proc = FallbackChainProcessor(processors=[set_fail, ok])
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)
    assert e.out_message.body == "ok"
    assert e.properties.get("fallback_used") == 1


# =============================================================================
# CircuitBreakerProcessor
# =============================================================================


def _make_mock_breaker(state: str = "closed", side_effect: Any = None) -> MagicMock:
    mock_breaker = MagicMock()
    mock_breaker.state = state
    mock_breaker.guard = MagicMock()
    mock_breaker.guard.return_value.__aenter__ = AsyncMock(side_effect=side_effect)
    mock_breaker.guard.return_value.__aexit__ = AsyncMock(return_value=False)
    return mock_breaker


@pytest.mark.asyncio
async def test_circuit_breaker_success() -> None:
    """Успешный sub-pipeline → cb_state в properties."""
    ok = DummyProcessor("ok")
    proc = CircuitBreakerProcessor(processors=[ok])
    ctx = AsyncMock()
    e = _ex(body=1)

    mock_breaker = _make_mock_breaker("closed")

    with patch("src.backend.core.resilience.breaker.get_breaker_registry") as mock_reg:
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_breaker
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    assert e.properties.get("cb_state") == "closed"
    assert e.status != ExchangeStatus.failed


@pytest.mark.asyncio
async def test_circuit_breaker_open_no_fallback() -> None:
    """CircuitOpen без fallback → exchange.fail."""
    ok = DummyProcessor("ok")
    proc = CircuitBreakerProcessor(processors=[ok])
    ctx = AsyncMock()
    e = _ex(body=1)

    from src.backend.core.resilience.breaker import CircuitOpen

    mock_breaker = _make_mock_breaker("open", side_effect=CircuitOpen("open"))

    with patch("src.backend.core.resilience.breaker.get_breaker_registry") as mock_reg:
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_breaker
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert "Circuit breaker is OPEN" in (e.error or "")
    assert e.properties.get("cb_state") == "open"


@pytest.mark.asyncio
async def test_circuit_breaker_open_with_fallback() -> None:
    """CircuitOpen с fallback → fallback выполняется."""
    ok = DummyProcessor("ok")
    fallback = DummyProcessor("fallback")
    proc = CircuitBreakerProcessor(processors=[ok], fallback_processors=[fallback])
    ctx = AsyncMock()
    e = _ex(body=1)

    from src.backend.core.resilience.breaker import CircuitOpen

    mock_breaker = _make_mock_breaker("open_fallback", side_effect=CircuitOpen("open"))

    with patch("src.backend.core.resilience.breaker.get_breaker_registry") as mock_reg:
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_breaker
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    assert e.out_message.body == "fallback"
    assert e.properties.get("cb_state") == "open_fallback"


@pytest.mark.asyncio
async def test_circuit_breaker_subpipeline_failure() -> None:
    """Sub-pipeline failed → _SubPipelineFailure, cb_state обновляется."""
    set_fail = SetFailProcessor("err")
    proc = CircuitBreakerProcessor(processors=[set_fail])
    ctx = AsyncMock()
    e = _ex(body=1)

    mock_breaker = _make_mock_breaker("half-open")

    with patch("src.backend.core.resilience.breaker.get_breaker_registry") as mock_reg:
        mock_registry = MagicMock()
        mock_registry.get_or_create.return_value = mock_breaker
        mock_reg.return_value = mock_registry
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    assert e.properties.get("cb_state") == "half-open"


@pytest.mark.asyncio
async def test_circuit_breaker_name_override() -> None:
    """breaker_name задаёт фиксированное имя."""
    proc = CircuitBreakerProcessor(processors=[], breaker_name="my_breaker")
    e = _ex(body=1)
    assert proc._resolve_breaker_name(e) == "my_breaker"


@pytest.mark.asyncio
async def test_circuit_breaker_default_name() -> None:
    """Без override имя формируется из route_id."""
    proc = CircuitBreakerProcessor(processors=[])
    e = _ex(body=1)
    e.meta.route_id = "route_42"
    assert proc._resolve_breaker_name(e) == "dsl.pipeline.route_42"


# =============================================================================
# TimeoutProcessor
# =============================================================================


@pytest.mark.asyncio
async def test_timeout_success() -> None:
    """Sub-pipeline укладывается в timeout → успех."""
    ok = DummyProcessor("ok")
    proc = TimeoutProcessor(processors=[ok], seconds=10)
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)
    assert e.out_message.body == "ok"
    assert e.properties.get("timeout_exceeded") is None


class SlowProcessor(BaseProcessor):
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        import asyncio

        await asyncio.sleep(10)


@pytest.mark.asyncio
async def test_timeout_exceeded_no_fallback() -> None:
    """Timeout без fallback → exchange.fail."""
    proc = TimeoutProcessor(processors=[SlowProcessor()], seconds=0.001)
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)

    assert e.properties.get("timeout_exceeded") is True
    assert e.status == ExchangeStatus.failed
    assert "Timeout after 0.001s" in (e.error or "")


@pytest.mark.asyncio
async def test_timeout_exceeded_with_fallback() -> None:
    """Timeout с fallback → fallback выполняется."""
    fallback = DummyProcessor("fallback")
    proc = TimeoutProcessor(
        processors=[SlowProcessor()], seconds=0.001, fallback_processors=[fallback]
    )
    ctx = AsyncMock()
    e = _ex(body=1)

    await proc.process(e, ctx)

    assert e.properties.get("timeout_exceeded") is True
    assert e.out_message.body == "fallback"
    assert e.status != ExchangeStatus.failed
