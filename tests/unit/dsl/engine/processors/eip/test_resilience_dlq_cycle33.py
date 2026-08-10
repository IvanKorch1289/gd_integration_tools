"""B-06 fix (cycle 33): 3-stage DLQ fallback — регрессионные тесты.

Покрывает контракт ``DeadLetterProcessor._send_to_dlq``:

* Stage 1: ``redis_client.add_to_stream`` (primary, hot-path).
* Stage 2: ``JsonlAuditBackend.append`` (JSONL, capability-gated по
  ``dlq_path``).
* Stage 3: терминальный отказ — ``dlq_send_failed_total`` + critical log +
  ``RuntimeError``. Никаких silent loss.

Паттерн: моки ставятся на network boundary (redis_client), а НЕ на
тестируемый метод. JSONL-бэкенд — реальный ``JsonlAuditBackend`` поверх
``tmp_path`` (без mock, см. project rule "If a dependency requires
external service — mock at the network boundary, not at the
function-under-test").
"""


from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.observability.metrics import dlq_send_failed_total
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.eip.resilience import DeadLetterProcessor


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    """Helper — собрать тестовый Exchange с заданным body/headers."""
    return Exchange(in_message=Message(body=body, headers=headers or {}))


class _SetFailProcessor(BaseProcessor):
    """Стандартный фейл-процессор: выставляет exchange.fail()."""

    def __init__(self, error: str = "boom", name: str | None = None) -> None:
        super().__init__(name=name or "set_fail")
        self._error = error

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.fail(self._error)


def _read_counter(metric: Any, stage: str) -> float:
    """Текущее значение ``dlq_send_failed_total{stage=stage}`` (best-effort)."""
    try:
        return metric.labels(stage=stage)._value.get()  # type: ignore[attr-defined]
    except Exception:
        return 0.0


# =============================================================================
# Stage 1: Redis primary path — happy path preserved
# =============================================================================


@pytest.mark.asyncio
async def test_stage1_redis_happy_path_no_metric_incremented() -> None:
    """Stage 1 успешен → Stage 2/3 не запускаются, метрика не инкрементится."""
    before = _read_counter(dlq_send_failed_total, "primary")
    failing = _SetFailProcessor("boom")
    proc = DeadLetterProcessor(processors=[failing], dlq_stream="my-dlq")
    ctx = AsyncMock()
    e = _ex(body={"id": 1})

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client",
    ) as mock_redis:
        mock_redis.add_to_stream = AsyncMock(return_value=None)
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    mock_redis.add_to_stream.assert_called_once()
    assert mock_redis.add_to_stream.call_args.kwargs["stream_name"] == "my-dlq"
    assert _read_counter(dlq_send_failed_total, "primary") == before


# =============================================================================
# Stage 1 fail → Stage 2 (JSONL) — fallback writes to local file
# =============================================================================


@pytest.mark.asyncio
async def test_stage2_jsonl_fallback_writes_to_local_file(
    tmp_path: Any,
) -> None:
    """Stage 1 падает + dlq_path задан → Stage 2 пишет в JSONL, raise нет."""
    failing = _SetFailProcessor("boom")
    dlq_file = tmp_path / "dlq.jsonl"
    proc = DeadLetterProcessor(
        processors=[failing], dlq_stream="primary-down", dlq_path=str(dlq_file),
    )
    ctx = AsyncMock()
    e = _ex(body={"order_id": 42}, headers={"x-trace": "abc"})

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client",
    ) as mock_redis:
        mock_redis.add_to_stream.side_effect = RuntimeError("redis offline")
        # Должен отработать без raise — Stage 2 успешен.
        await proc.process(e, ctx)

    assert e.status == ExchangeStatus.failed
    mock_redis.add_to_stream.assert_called_once()
    assert dlq_file.exists(), "JSONL DLQ-файл должен быть создан Stage 2"
    lines = dlq_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    record = json.loads(lines[0])
    assert record["event"] == "dsl.dlq"
    assert record["action"] == "dlq_send_fallback_jsonl"
    assert record["entity_id"] == e.meta.exchange_id
    assert record["metadata"]["dlq_reason"] == "redis_unavailable"
    assert "RuntimeError" in record["metadata"]["stage1_error"]
    # Контекст исходного DLQ-entry сохранён в ``after``:
    after = record["after"]
    assert after["exchange_id"] == e.meta.exchange_id
    assert after["error"] == "boom"


# =============================================================================
# Stage 1 + Stage 2 fail → Stage 3 (terminal)
# =============================================================================


@pytest.mark.asyncio
async def test_stage3_terminal_raises_when_all_stages_fail(
    tmp_path: Any,
) -> None:
    """Stage 1 fail + Stage 2 fail → RuntimeError + critical log + metric."""
    failing = _SetFailProcessor("boom")
    dlq_file = tmp_path / "dlq_terminal.jsonl"
    proc = DeadLetterProcessor(
        processors=[failing], dlq_stream="down", dlq_path=str(dlq_file),
    )
    ctx = AsyncMock()
    e = _ex(body=1)
    before_all = _read_counter(dlq_send_failed_total, "all")

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client",
    ) as mock_redis:
        mock_redis.add_to_stream.side_effect = RuntimeError("redis down")
        # Stage 2 тоже падает — патчим ``importlib.import_module`` через
        # подмену модуля jsonl_audit: ``JsonlAuditBackend.append`` бросает.
        with patch(
            "src.backend.infrastructure.audit.jsonl_audit.JsonlAuditBackend.append",
            new=AsyncMock(side_effect=OSError("disk full")),
        ), pytest.raises(RuntimeError) as exc_info:
            await proc.process(e, ctx)

    msg = str(exc_info.value)
    assert "DLQ send failed" in msg
    assert "redis=" in msg
    assert "jsonl=" in msg
    # ``__cause__`` — Stage 1 exception (per ``raise ... from stage1_error``).
    assert isinstance(exc_info.value.__cause__, RuntimeError)
    assert "redis down" in str(exc_info.value.__cause__)

    after_all = _read_counter(dlq_send_failed_total, "all")
    assert after_all == before_all + 1, (
        f"dlq_send_failed_total{{stage=all}} должен инкрементнуться: "
        f"before={before_all}, after={after_all}"
    )


# =============================================================================
# Stage 1 fail + dlq_path=None → Stage 3 (primary-only)
# =============================================================================


@pytest.mark.asyncio
async def test_stage3_terminal_when_no_dlq_path_configured() -> None:
    """Stage 1 fail + dlq_path=None → RuntimeError + metric{stage=primary}."""
    failing = _SetFailProcessor("boom")
    proc = DeadLetterProcessor(processors=[failing])  # dlq_path=None default
    ctx = AsyncMock()
    e = _ex(body=1)
    before_primary = _read_counter(dlq_send_failed_total, "primary")

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client",
    ) as mock_redis:
        mock_redis.add_to_stream.side_effect = RuntimeError("redis down")
        with pytest.raises(RuntimeError) as exc_info:
            await proc.process(e, ctx)

    msg = str(exc_info.value)
    assert "DLQ send failed" in msg
    assert "redis=" in msg
    assert "jsonl=" in msg
    assert "not_configured" in msg

    after_primary = _read_counter(dlq_send_failed_total, "primary")
    assert after_primary == before_primary + 1, (
        f"dlq_send_failed_total{{stage=primary}} должен инкрементнуться: "
        f"before={before_primary}, after={after_primary}"
    )


# =============================================================================
# Успешный sub-pipeline → DLQ не вызывается вообще
# =============================================================================


class _OkProcessor(BaseProcessor):
    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        exchange.out_message = Message(body="ok")


@pytest.mark.asyncio
async def test_no_dlq_invocation_on_success() -> None:
    """Успешный sub-pipeline → _send_to_dlq не вызывается, метрика 0."""
    ok = _OkProcessor()
    proc = DeadLetterProcessor(processors=[ok], dlq_path="/tmp/should-not-exist.jsonl")
    ctx = AsyncMock()
    e = _ex(body=1)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.redis_client",
    ) as mock_redis:
        mock_redis.add_to_stream = AsyncMock(return_value=None)
        await proc.process(e, ctx)

    assert e.status != ExchangeStatus.failed
    mock_redis.add_to_stream.assert_not_called()
