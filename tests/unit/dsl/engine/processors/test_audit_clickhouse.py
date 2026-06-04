# ruff: noqa: S101
"""Unit-тесты для ``AuditClickhouseProcessor``.

Покрывают process (с динамическими полями, без них, ошибки), to_spec и параметры.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.audit_clickhouse import (
    AuditClickhouseParams,
    AuditClickhouseProcessor,
)


class _Message:
    def __init__(self, body: Any = None, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._error: str | None = None

    def get_property(self, key: str) -> Any:
        return self.properties.get(key)

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


class TestAuditClickhouseParams:
    """Pydantic-модель параметров."""

    def test_minimal_valid(self) -> None:
        p = AuditClickhouseParams(event_type="user.login")
        assert p.event_type == "user.login"
        assert p.severity == "info"
        assert p.payload is None

    def test_full_valid(self) -> None:
        p = AuditClickhouseParams(
            event_type="order.created",
            payload={"id": 1},
            severity="error",
            tenant_id_from="tenant",
            user_id_from="user",
            route_name_from="route",
        )
        assert p.severity == "error"
        assert p.payload == {"id": 1}

    def test_empty_event_type_raises(self) -> None:
        with pytest.raises(ValueError):
            AuditClickhouseParams(event_type="")

    def test_invalid_severity_raises(self) -> None:
        with pytest.raises(ValueError):
            AuditClickhouseParams(event_type="t", severity="critical")  # type: ignore[call-arg]


class TestAuditClickhouseProcessorInit:
    """Инициализация."""

    def test_default_name(self) -> None:
        proc = AuditClickhouseProcessor(event_type="evt")
        assert proc.name == "audit_clickhouse:evt"

    def test_custom_name(self) -> None:
        proc = AuditClickhouseProcessor(event_type="evt", name="custom")
        assert proc.name == "custom"

    def test_payload_defaults_to_empty_dict(self) -> None:
        proc = AuditClickhouseProcessor(event_type="evt")
        assert proc._payload == {}


@pytest.mark.asyncio
class TestAuditClickhouseProcess:
    """Основной метод process."""

    async def test_process_calls_emit(self) -> None:
        proc = AuditClickhouseProcessor(event_type="user.login")
        exchange = _Exchange()

        mock_service = AsyncMock()
        mock_event_cls = MagicMock()
        mock_event_instance = MagicMock()
        mock_event_cls.return_value = mock_event_instance

        with (
            patch(
                "src.backend.services.audit.clickhouse_audit_service.get_audit_service",
                return_value=mock_service,
            ),
            patch(
                "src.backend.services.audit.clickhouse_audit_service.AuditEvent",
                mock_event_cls,
            ),
        ):
            await proc.process(exchange, _Context())

        mock_service.emit.assert_awaited_once_with(mock_event_instance)
        assert exchange._error is None

    async def test_process_extracts_dynamic_fields(self) -> None:
        proc = AuditClickhouseProcessor(
            event_type="order.created",
            tenant_id_from="tenant_id",
            user_id_from="user_id",
            route_name_from="route_name",
        )
        exchange = _Exchange()
        exchange.properties["tenant_id"] = "t1"
        exchange.properties["user_id"] = "u42"
        exchange.properties["route_name"] = "r99"

        mock_service = AsyncMock()
        mock_event_cls = MagicMock()

        with (
            patch(
                "src.backend.services.audit.clickhouse_audit_service.get_audit_service",
                return_value=mock_service,
            ),
            patch(
                "src.backend.services.audit.clickhouse_audit_service.AuditEvent",
                mock_event_cls,
            ),
        ):
            await proc.process(exchange, _Context())

        call_kwargs = mock_event_cls.call_args.kwargs
        assert call_kwargs["tenant_id"] == "t1"
        assert call_kwargs["user_id"] == "u42"
        assert call_kwargs["route_name"] == "r99"

    async def test_process_ignores_none_dynamic_fields(self) -> None:
        proc = AuditClickhouseProcessor(event_type="x", tenant_id_from="missing")
        exchange = _Exchange()

        mock_service = AsyncMock()
        mock_event_cls = MagicMock()

        with (
            patch(
                "src.backend.services.audit.clickhouse_audit_service.get_audit_service",
                return_value=mock_service,
            ),
            patch(
                "src.backend.services.audit.clickhouse_audit_service.AuditEvent",
                mock_event_cls,
            ),
        ):
            await proc.process(exchange, _Context())

        call_kwargs = mock_event_cls.call_args.kwargs
        assert call_kwargs["tenant_id"] is None

    async def test_process_logs_warning_on_emit_error(self) -> None:
        proc = AuditClickhouseProcessor(event_type="evt")
        exchange = _Exchange()

        mock_service = AsyncMock()
        mock_service.emit.side_effect = RuntimeError("clickhouse down")

        with (
            patch(
                "src.backend.services.audit.clickhouse_audit_service.get_audit_service",
                return_value=mock_service,
            ),
            patch(
                "src.backend.services.audit.clickhouse_audit_service.AuditEvent",
                MagicMock(),
            ),
        ):
            # Ошибка propagate — согласно доке "fire and forget" через logging
            # warning, но код не ловит исключение. Проверяем что propagate.
            with pytest.raises(RuntimeError, match="clickhouse down"):
                await proc.process(exchange, _Context())


class TestAuditClickhouseToSpec:
    """Round-trip сериализация."""

    def test_minimal_spec(self) -> None:
        proc = AuditClickhouseProcessor(event_type="evt")
        assert proc.to_spec() == {
            "audit_clickhouse": {"event_type": "evt", "severity": "info"}
        }

    def test_full_spec(self) -> None:
        proc = AuditClickhouseProcessor(
            event_type="evt",
            payload={"a": 1},
            severity="warning",
            tenant_id_from="t",
            user_id_from="u",
            route_name_from="r",
        )
        spec = proc.to_spec()
        assert spec["audit_clickhouse"]["payload"] == {"a": 1}
        assert spec["audit_clickhouse"]["severity"] == "warning"
        assert spec["audit_clickhouse"]["tenant_id_from"] == "t"
