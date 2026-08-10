"""D-A3-02 fix (cycle 1): ClickHouseAuditService silent-loss observability.

Проверяет, что при silent-loss пути (нет DLQ writer, нет DLQ JSONL path)
ClickHouseAuditService эмитит:
- logger.critical со structured payload (event_id, transport, error);
- инкрементирует Prometheus counter audit_silent_loss_total.

Раньше silent return без observability → production data-loss без алертинга.
"""


from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.observability.metrics import audit_silent_loss_total
from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
)


def _make_event(**kwargs: Any) -> AuditEvent:
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 8, 7, 12, 0, 0, tzinfo=UTC),
        "event_type": "test.silent.loss",
        "tenant_id": "tenant-da302",
        "user_id": "user-1",
        "route_name": "/api/v1/audit",
        "payload": {"k": "v"},
        "severity": "info",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


def _failing_client() -> AsyncMock:
    client = AsyncMock()
    client.insert = AsyncMock(
        side_effect=RuntimeError("ClickHouse unavailable")
    )
    return client


def _flags_on() -> MagicMock:
    flags = MagicMock()
    flags.audit_clickhouse_enabled = True
    return flags


def _counter_value(reason: str = "no_dlq_configured") -> float:
    """Текущее значение audit_silent_loss_total для transport=clickhouse_audit."""
    return audit_silent_loss_total.labels(
        transport="clickhouse_audit", reason=reason
    )._value.get()


class TestClickHouseAuditSilentLossMetric:
    """D-A3-02 fix (cycle 1): silent-loss observability."""

    @pytest.mark.asyncio
    async def test_silent_loss_emits_critical_log(self) -> None:
        """Silent-loss → _logger.critical вызывается с structured payload."""
        service = ClickHouseAuditService(client=_failing_client())
        event = _make_event(event_id="da302-single")

        with patch("src.backend.core.config.features.feature_flags", _flags_on()):
            with patch(
                "src.backend.services.audit.clickhouse_audit_service.service._logger"
            ) as mock_logger:
                await service.emit(event)

        mock_logger.critical.assert_called_once()
        fmt = mock_logger.critical.call_args[0][0]
        assert "audit_silent_loss" in fmt

    @pytest.mark.asyncio
    async def test_silent_loss_increments_counter(self) -> None:
        """Silent-loss → audit_silent_loss_total counter +1."""
        service = ClickHouseAuditService(client=_failing_client())
        before = _counter_value()

        with patch("src.backend.core.config.features.feature_flags", _flags_on()):
            await service.emit(_make_event())

        assert _counter_value() == before + 1

    @pytest.mark.asyncio
    async def test_silent_loss_payload_structure(self) -> None:
        """extra= содержит transport, reason, lost_count, event_ids, tenant_ids, error_class, error_message."""
        service = ClickHouseAuditService(client=_failing_client())
        event = _make_event(event_id="da302-payload", tenant_id="t-payload")

        with patch("src.backend.core.config.features.feature_flags", _flags_on()):
            with patch(
                "src.backend.services.audit.clickhouse_audit_service.service._logger"
            ) as mock_logger:
                await service.emit(event)

        call_kwargs = mock_logger.critical.call_args.kwargs
        extra = call_kwargs.get("extra", {})
        assert extra["transport"] == "clickhouse_audit"
        assert extra["reason"] == "no_dlq_configured"
        assert extra["lost_count"] == 1
        assert "da302-payload" in extra["event_ids"]
        assert "t-payload" in extra["tenant_ids"]
        assert extra["error_class"] == "RuntimeError"
        assert "ClickHouse unavailable" in extra["error_message"]

    @pytest.mark.asyncio
    async def test_silent_loss_not_triggered_when_dlq_writer_set(self) -> None:
        """Если dlq_writer сконфигурирован → critical log НЕ эмитится, counter НЕ inc."""
        from src.backend.infrastructure.messaging.dlq.memory_writer import (
            InMemoryDLQWriter,
        )

        writer = InMemoryDLQWriter()
        service = ClickHouseAuditService(
            client=_failing_client(), dlq_writer=writer
        )
        before = _counter_value()

        with patch("src.backend.core.config.features.feature_flags", _flags_on()):
            with patch(
                "src.backend.services.audit.clickhouse_audit_service.service._logger"
            ) as mock_logger:
                await service.emit(_make_event())

        mock_logger.critical.assert_not_called()
        assert _counter_value() == before
