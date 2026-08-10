"""Регрессионные тесты DLQ-fallback для :class:`ClickHouseAuditService` (B-series 2026-08-03).

Покрывает:
    1. ``test_emit_falls_back_to_dlq_on_clickhouse_failure`` — при сбое
       ``client.insert()`` и наличии ``dlq_path`` событие персистится в
       JSONL (через :class:`JsonlAuditBackend`).
    2. ``test_emit_batch_falls_back_to_dlq_on_clickhouse_failure`` — то же
       для batch-insert: все события пакета пишутся в DLQ при failure.
    3. ``test_successful_emit_does_not_write_dlq`` — success-path не
       задевает JSONL (no false-positive DLQ).
    4. ``test_no_dlq_when_path_not_set_legacy_silent_loss`` — без ``dlq_path``
       поведение остаётся legacy (silent loss + WARNING), backward-compat.
    5. ``test_dlq_fallback_survives_dlq_write_failure`` — даже если сама
       DLQ-запись упала (например, невалидный path), исключение НЕ
       пробрасывается в caller (fire-and-forget семантика сохранена).
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone, UTC
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
)


def _make_event(**kwargs: Any) -> AuditEvent:
    """Строит минимальный AuditEvent для тестов."""
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC),
        "event_type": "test.dlq.event",
        "tenant_id": "tenant-1",
        "user_id": "user-42",
        "route_name": "/api/v1/test",
        "payload": {"key": "value"},
        "severity": "info",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


def _make_failing_client() -> AsyncMock:
    """AsyncMock-клиент ClickHouse, ``insert()`` всегда кидает RuntimeError."""
    client = AsyncMock()
    client.insert = AsyncMock(
        side_effect=RuntimeError("ClickHouse unavailable: connection refused")
    )
    return client


def _flags_on() -> MagicMock:
    """feature_flags с audit_clickhouse_enabled=True."""
    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = True
    return mock_flags


# ─── Тест 1: emit fallback в DLQ ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_falls_back_to_dlq_on_clickhouse_failure(tmp_path: Path) -> None:
    """emit() при сбое ClickHouse → событие пишется в JSONL DLQ."""
    dlq_path = tmp_path / "dlq.jsonl"
    service = ClickHouseAuditService(client=_make_failing_client(), dlq_path=dlq_path)
    event = _make_event(event_id="dlq-test-1", event_type="order.created")

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        # Должно отработать без raise — fire-and-forget семантика.
        await service.emit(event)

    # JSONL-файл создан, содержит ровно одну запись.
    assert dlq_path.exists()
    lines = dlq_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    record = json.loads(lines[0])
    # JsonlAuditBackend-формат: who/what/event/entity_id/after.
    assert record["event"] == "order.created"
    assert record["entity_id"] == "dlq-test-1"
    assert record["action"] == "clickhouse_emit_failed"
    assert record["metadata"]["dlq_reason"] == "clickhouse_unavailable"
    assert "connection refused" in record["metadata"]["clickhouse_error"]
    # Original row сохранён в after (для replay).
    assert record["after"]["event_id"] == "dlq-test-1"
    assert record["after"]["event_type"] == "order.created"


# ─── Тест 2: emit_batch fallback в DLQ ────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_batch_falls_back_to_dlq_on_clickhouse_failure(
    tmp_path: Path,
) -> None:
    """emit_batch() при сбое ClickHouse → ВСЕ события пакета пишутся в JSONL DLQ."""
    dlq_path = tmp_path / "dlq_batch.jsonl"
    service = ClickHouseAuditService(client=_make_failing_client(), dlq_path=dlq_path)
    events = [
        _make_event(event_id=f"batch-{i}", event_type="test.batch") for i in range(5)
    ]

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit_batch(events)

    assert dlq_path.exists()
    lines = dlq_path.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 5, f"Ожидалось 5 DLQ-записей, получено {len(lines)}"

    # Проверяем, что все event_id сохранены.
    saved_ids = set()
    for line in lines:
        record = json.loads(line)
        saved_ids.add(record["entity_id"])
    assert saved_ids == {f"batch-{i}" for i in range(5)}


# ─── Тест 3: success-path не задевает DLQ ──────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_emit_does_not_write_dlq(tmp_path: Path) -> None:
    """Успешный ClickHouse insert не создаёт DLQ-файл (no false-positive)."""
    dlq_path = tmp_path / "should_not_exist.jsonl"

    # Клиент, который успешно выполняет insert.
    ok_client = AsyncMock()
    ok_client.insert = AsyncMock(return_value=None)

    service = ClickHouseAuditService(client=ok_client, dlq_path=dlq_path)
    event = _make_event()

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit(event)

    # DLQ-файл НЕ должен быть создан при success.
    assert not dlq_path.exists(), (
        f"DLQ-файл не должен создаваться при success-path: {dlq_path}"
    )
    ok_client.insert.assert_called_once()


# ─── Тест 4: legacy silent-loss при dlq_path=None ─────────────────────────────


@pytest.mark.asyncio
async def test_no_dlq_when_path_not_set_legacy_silent_loss(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Без dlq_path поведение остаётся legacy (WARNING + silent loss)."""
    service = ClickHouseAuditService(client=_make_failing_client())
    event = _make_event(event_id="legacy-1")

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        # Должен отработать без raise.
        with caplog.at_level("WARNING", logger="services.audit.clickhouse"):
            await service.emit(event)

    # WARNING о сбое ClickHouse — legacy-логирование.
    assert any(
        "ClickHouseAuditService.emit failed" in r.message for r in caplog.records
    ), "Ожидался WARNING о сбое ClickHouse"


# ─── Тест 5: DLQ-сбой не пробрасывается (defense-in-depth) ─────────────────────


@pytest.mark.asyncio
async def test_dlq_fallback_survives_dlq_write_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Если DLQ-запись тоже упала — исключение не пробрасывается в caller.

    Fire-and-forget семантика сохранена: caller (audit-middleware) не должен
    получать исключение от audit-фреймворка (иначе бизнес-pipeline валится
    из-за сбоя observability).
    """
    # Подменяем JsonlAuditBackend на broken — метод append() кидает.
    broken_backend = MagicMock()
    broken_backend.append = AsyncMock(
        side_effect=OSError("disk full or permission denied")
    )

    with patch(
        "src.backend.infrastructure.audit.jsonl_audit.JsonlAuditBackend",
        return_value=broken_backend,
    ):
        service = ClickHouseAuditService(
            client=_make_failing_client(), dlq_path=Path("/tmp/never_written.jsonl")
        )
        event = _make_event(event_id="dlq-fail-1")

        with patch("src.backend.core.config.features.feature_flags", _flags_on()):
            with caplog.at_level("ERROR", logger="services.audit.clickhouse"):
                # Не должен raise'ить — caller (audit-middleware) не валится.
                await service.emit(event)

    # ERROR-лог о потере события (для forensic).
    assert any("DLQ fallback failed" in r.message for r in caplog.records), (
        f"Ожидался ERROR о DLQ failure, got: {[r.message for r in caplog.records]}"
    )


# ─── Тест 6: пустой batch не пишет в DLQ (no-op) ──────────────────────────────


@pytest.mark.asyncio
async def test_emit_batch_empty_does_not_write_dlq(tmp_path: Path) -> None:
    """Пустой список событий в emit_batch() → DLQ-файл не создаётся."""
    dlq_path = tmp_path / "empty.jsonl"
    service = ClickHouseAuditService(client=_make_failing_client(), dlq_path=dlq_path)

    with patch("src.backend.core.config.features.feature_flags", _flags_on()):
        await service.emit_batch([])

    # Empty batch → ClickHouse не дёргается, DLQ не пишется.
    assert not dlq_path.exists()


# ─── Тест 7: feature flag OFF → DLQ не задействован ────────────────────────────


@pytest.mark.asyncio
async def test_emit_off_flag_does_not_write_dlq(tmp_path: Path) -> None:
    """audit_clickhouse_enabled=False → ClickHouse skip + DLQ skip (no-op)."""
    dlq_path = tmp_path / "off.jsonl"
    service = ClickHouseAuditService(client=_make_failing_client(), dlq_path=dlq_path)
    event = _make_event()

    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = False

    with patch("src.backend.core.config.features.feature_flags", mock_flags):
        await service.emit(event)

    # ClickHouse skip (flag=OFF), DLQ не нужен.
    assert not dlq_path.exists()
