# ruff: noqa: S101
"""Unit tests for WebhookRelay DLQ lifecycle (services/integrations/webhook_relay.py).

cycle-8/D-AUDIT-802 — фикс silent-loss в DLQ:

* (a) ``_memory_dlq`` ограничен ``deque(maxlen=_DLQ_MAX_LEN)``;
* (b) ``_dlq_remove`` логирует LREM-сбои на уровне ``error`` + ``exc_info``;
* (c) ``dlq_retry`` переносит ``rule_not_found`` записи в отдельный
  ``_dead_rule_dlq`` (тоже bounded) и удаляет их из основной очереди.

Тесты используют ``_redis_raw`` mock чтобы Redis не требовался.
"""

from __future__ import annotations

from collections import deque
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.services.integrations.webhook_relay import (
    _DLQ_MAX_LEN,
    DLQEntry,
    RelayRule,
    WebhookRelay,
)

# ── Helpers ─────────────────────────────────────────────────────


def _make_relay() -> WebhookRelay:
    """Возвращает чистый relay (без Redis)."""
    return WebhookRelay()


def _entry(rule_id: str = "r1", error: str = "boom") -> DLQEntry:
    return DLQEntry(rule_id=rule_id, payload={"x": 1}, error=error, attempts=3)


def _rule(rule_id: str = "r1") -> RelayRule:
    return RelayRule(
        id=rule_id,
        event_type="evt",
        target_url="https://example.invalid/hook",
    )


# ── (a) Bounded LRU queue ───────────────────────────────────────


def test_memory_dlq_is_bounded_deque() -> None:
    """``_memory_dlq`` должен быть ``deque(maxlen=_DLQ_MAX_LEN)``."""
    relay = _make_relay()
    assert isinstance(relay._memory_dlq, deque)
    assert relay._memory_dlq.maxlen == _DLQ_MAX_LEN


def test_memory_dlq_evicts_oldest_on_overflow() -> None:
    """При переполнении deque(maxlen=...) вытесняет самые старые записи."""
    relay = _make_relay()
    relay._memory_dlq = deque(maxlen=3)
    for i in range(5):
        relay._memory_dlq.append(DLQEntry(id=f"e{i}", rule_id="r", payload={}))
    assert len(relay._memory_dlq) == 3
    ids = [e.id for e in relay._memory_dlq]
    assert ids == ["e2", "e3", "e4"]  # e0, e1 evicted


def test_memory_dlq_remove_rebuilds_bounded() -> None:
    """``_dlq_remove`` для memory-fallback должен сохранять bounded cap."""
    relay = _make_relay()
    for i in range(3):
        relay._memory_dlq.append(DLQEntry(id=f"e{i}", rule_id="r", payload={}))

    async def _run() -> None:
        with patch(
            "src.backend.services.integrations.webhook_relay._redis_raw",
            new_callable=AsyncMock,
            return_value=None,
        ):
            await relay._dlq_remove("e1")

    import asyncio

    asyncio.run(_run())
    ids = [e.id for e in relay._memory_dlq]
    assert ids == ["e0", "e2"]
    assert isinstance(relay._memory_dlq, deque)
    # Production rebuild использует _DLQ_MAX_LEN как maxlen (контрактный cap).
    assert relay._memory_dlq.maxlen == _DLQ_MAX_LEN


# ── (b) Explicit DLQ error handling + logger.error ─────────────


def test_dlq_remove_logs_error_on_lrem_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """LREM-сбой должен логироваться на уровне ``error`` с ``exc_info``."""
    relay = _make_relay()

    fake_raw = AsyncMock()
    fake_raw.lrange = AsyncMock(side_effect=RuntimeError("redis is down"))

    async def _run() -> None:
        with (
            patch(
                "src.backend.services.integrations.webhook_relay._redis_raw",
                new_callable=AsyncMock,
                return_value=fake_raw,
            ),
            caplog.at_level("ERROR", logger="src.backend.services.integrations.webhook_relay"),
        ):
            await relay._dlq_remove("e123")

    import asyncio

    asyncio.run(_run())

    error_records = [
        r for r in caplog.records if r.levelname == "ERROR"
    ]
    assert error_records, "expected ERROR log on LREM failure"
    assert any(
        "DLQ Redis remove failed" in r.getMessage() for r in error_records
    )
    # exc_info=True → record.exc_info не пустой
    assert any(r.exc_info is not None for r in error_records)


# ── (c) TTL/dead-letter queue for dlq_retry ─────────────────────


def test_dead_rule_dlq_is_bounded_deque() -> None:
    """``_dead_rule_dlq`` — отдельная bounded очередь."""
    relay = _make_relay()
    assert isinstance(relay._dead_rule_dlq, deque)
    assert relay._dead_rule_dlq.maxlen == _DLQ_MAX_LEN
    assert len(relay._dead_rule_dlq) == 0


def test_dlq_retry_rule_not_found_moves_to_dead_rule_queue() -> None:
    """``rule_not_found`` → запись переносится в ``_dead_rule_dlq``."""
    relay = _make_relay()
    relay._rules["live"] = _rule("live")
    live_entry = _entry(rule_id="live")
    dead_entry = _entry(rule_id="ghost-rule")
    relay._memory_dlq.append(live_entry)
    relay._memory_dlq.append(dead_entry)

    async def _run() -> dict[str, Any]:
        with patch(
            "src.backend.services.integrations.webhook_relay._redis_raw",
            new_callable=AsyncMock,
            return_value=None,
        ):
            # Мокаем _send_with_retry: live → success (чтобы не уходил в DLQ снова),
            # ghost-rule → не вызывается (rule отсутствует → rule_not_found path).
            relay._send_with_retry = AsyncMock(  # type: ignore[method-assign]
                return_value={
                    "rule_id": "live",
                    "status": "sent",
                    "status_code": 200,
                }
            )
            return await relay.dlq_retry()

    import asyncio

    result = asyncio.run(_run())

    # dead_entry перенесён в dead-rule queue, live_entry удалён после успеха.
    assert len(relay._memory_dlq) == 0
    assert len(relay._dead_rule_dlq) == 1
    assert relay._dead_rule_dlq[0].id == dead_entry.id

    # результат содержит маркер перемещения
    assert result["dead_rule_moved"] == 1
    rule_not_found_results = [
        r for r in result["results"] if r.get("status") == "rule_not_found"
    ]
    assert len(rule_not_found_results) == 1
    assert rule_not_found_results[0]["moved_to_dead_rule_queue"] is True


def test_dlq_retry_no_dead_leaves_main_dlq_intact() -> None:
    """Если все правила живые, dead_rule_moved == 0 и dead-rule queue пуст."""
    relay = _make_relay()
    relay._rules["r1"] = _rule("r1")
    entry = _entry(rule_id="r1")
    relay._memory_dlq.append(entry)

    async def _run() -> dict[str, Any]:
        with patch(
            "src.backend.services.integrations.webhook_relay._redis_raw",
            new_callable=AsyncMock,
            return_value=None,
        ):
            # Чтобы _send_with_retry не делал реальный HTTP — мокаем целиком.
            relay._send_with_retry = AsyncMock(  # type: ignore[method-assign]
                return_value={"rule_id": "r1", "status": "sent", "status_code": 200}
            )
            return await relay.dlq_retry()

    import asyncio

    result = asyncio.run(_run())
    assert result["dead_rule_moved"] == 0
    assert len(relay._dead_rule_dlq) == 0
    # main DLQ пуст (запись удалена после успешной retry)
    assert len(relay._memory_dlq) == 0


def test_dlq_list_includes_dead_rule_section() -> None:
    """``dlq_list`` должен возвращать dead-rule total + entries."""
    relay = _make_relay()
    relay._memory_dlq.append(_entry(rule_id="live"))
    relay._dead_rule_dlq.append(_entry(rule_id="ghost"))

    async def _run() -> dict[str, Any]:
        with patch(
            "src.backend.services.integrations.webhook_relay._redis_raw",
            new_callable=AsyncMock,
            return_value=None,
        ):
            return await relay.dlq_list()

    import asyncio

    out = asyncio.run(_run())
    assert out["total"] == 1
    assert out["dead_rule_total"] == 1
    assert len(out["dead_rule_entries"]) == 1
    assert out["dead_rule_entries"][0]["rule_id"] == "ghost"


def test_dlq_retry_bounded_dead_rule_queue() -> None:
    """``_dead_rule_dlq`` вытесняет самые старые записи при переполнении."""
    relay = _make_relay()
    relay._dead_rule_dlq = deque(maxlen=3)
    for i in range(5):
        relay._dead_rule_dlq.append(DLQEntry(id=f"d{i}", rule_id="ghost", payload={}))
    assert len(relay._dead_rule_dlq) == 3
    assert [e.id for e in relay._dead_rule_dlq] == ["d2", "d3", "d4"]
