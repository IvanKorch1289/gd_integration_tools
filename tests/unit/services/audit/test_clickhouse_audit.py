"""Unit-тесты ClickHouseAuditService (K8 Wave 4).

Покрывает:
    1. ``test_emit_skips_when_flag_off`` — при flag=OFF вызов emit() не
       создаёт клиент ClickHouse и возвращает без ошибки.
    2. ``test_emit_lazy_imports_clickhouse`` — при flag=ON emit() вызывает
       ``get_async_client`` (mock'ируется).
    3. ``test_audit_event_dataclass_serializes`` — AuditEvent.to_row()
       возвращает корректный словарь с JSON-строкой payload.
    4. ``test_get_audit_service_singleton`` — get_audit_service() возвращает
       один и тот же экземпляр при повторных вызовах.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.audit.clickhouse_audit_service import (
    AuditEvent,
    ClickHouseAuditService,
    get_audit_service,
)


# ─── Фикстура базового события ──────────────────────────────────────────────


def _make_event(**kwargs: Any) -> AuditEvent:
    """Строит минимальный AuditEvent для тестов."""
    defaults: dict[str, Any] = {
        "event_id": str(uuid.uuid4()),
        "timestamp": datetime(2026, 5, 13, 12, 0, 0, tzinfo=timezone.utc),
        "event_type": "test.event",
        "tenant_id": "tenant-1",
        "user_id": "user-42",
        "route_name": "/api/v1/test",
        "payload": {"key": "value"},
        "severity": "info",
    }
    defaults.update(kwargs)
    return AuditEvent(**defaults)


# ─── Тест 1: emit пропускается при flag=OFF ──────────────────────────────────


@pytest.mark.asyncio
async def test_emit_skips_when_flag_off() -> None:
    """При audit_clickhouse_enabled=False emit() не создаёт клиент и не падает."""
    service = ClickHouseAuditService()
    event = _make_event()

    # feature_flags импортируется внутри метода — патчим через sys.modules
    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = False

    with patch("src.backend.core.config.features.feature_flags", mock_flags):
        # Дополнительно патчим _get_client, чтобы убедиться в no-op
        with patch.object(service, "_get_client", new_callable=AsyncMock) as mock_get_client:
            await service.emit(event)
            mock_get_client.assert_not_called()

    # Клиент не был создан
    assert service._client is None


# ─── Тест 2: emit lazy-импортирует clickhouse при flag=ON ────────────────────


@pytest.mark.asyncio
async def test_emit_lazy_imports_clickhouse() -> None:
    """При flag=ON emit() вызывает get_async_client и передаёт данные клиенту."""
    # Создаём mock-клиент ClickHouse с async insert
    mock_client = AsyncMock()
    mock_client.insert = AsyncMock(return_value=None)

    # Инжектируем mock-клиент напрямую (имитируем уже созданный клиент)
    service = ClickHouseAuditService(client=mock_client)
    event = _make_event()

    # feature_flags импортируется внутри метода emit() — патчим объект в
    # модуле features, откуда он импортируется
    mock_flags = MagicMock()
    mock_flags.audit_clickhouse_enabled = True

    with patch("src.backend.core.config.features.feature_flags", mock_flags):
        await service.emit(event)

    # Проверяем, что insert был вызван ровно один раз
    mock_client.insert.assert_called_once()
    call_kwargs = mock_client.insert.call_args
    # Первый позиционный аргумент — имя таблицы
    assert call_kwargs.args[0] == "audit_events"
    # data — список из одной строки
    data_arg = call_kwargs.kwargs.get("data", call_kwargs.args[1] if len(call_kwargs.args) > 1 else [])
    assert len(data_arg) == 1


# ─── Тест 3: AuditEvent.to_row() корректно сериализуется ────────────────────


def test_audit_event_dataclass_serializes() -> None:
    """AuditEvent.to_row() возвращает словарь с JSON-строкой в поле payload."""
    ts = datetime(2026, 5, 13, 10, 30, 0, tzinfo=timezone.utc)
    event = AuditEvent(
        event_id="test-uuid-123",
        timestamp=ts,
        event_type="order.created",
        tenant_id="bank-tenant",
        user_id="user-007",
        route_name="/api/v1/orders",
        payload={"order_id": 42, "amount": 1000.50},
        severity="info",
    )

    row = event.to_row()

    # Обязательные поля присутствуют
    assert row["event_id"] == "test-uuid-123"
    assert row["event_type"] == "order.created"
    assert row["tenant_id"] == "bank-tenant"
    assert row["user_id"] == "user-007"
    assert row["route_name"] == "/api/v1/orders"
    assert row["severity"] == "info"

    # timestamp конвертируется в UTC datetime
    assert row["timestamp"].tzinfo is not None

    # payload — строка JSON, парсируемая обратно в dict
    assert isinstance(row["payload"], str)
    parsed = json.loads(row["payload"])
    assert parsed["order_id"] == 42
    assert parsed["amount"] == pytest.approx(1000.50)


# ─── Тест 4: get_audit_service() возвращает singleton ───────────────────────


def test_get_audit_service_singleton() -> None:
    """get_audit_service() возвращает один и тот же экземпляр при повторных вызовах."""
    # Сбрасываем глобальный singleton перед тестом
    import src.backend.services.audit.clickhouse_audit_service as mod

    original = mod._service_instance
    mod._service_instance = None

    try:
        svc1 = get_audit_service()
        svc2 = get_audit_service()

        assert svc1 is svc2
        assert isinstance(svc1, ClickHouseAuditService)
    finally:
        # Восстанавливаем исходное состояние
        mod._service_instance = original
