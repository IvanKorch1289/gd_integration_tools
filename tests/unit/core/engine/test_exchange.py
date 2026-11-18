"""Тесты core-моделей Exchange и совместимого DSL re-export."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.engine.exchange import Exchange as CoreExchange
from src.backend.core.engine.exchange import ExchangeStatus as CoreExchangeStatus
from src.backend.core.engine.exchange import Message as CoreMessage
from src.backend.core.types.data_kind import DataKind
from src.backend.dsl.engine.exchange import Exchange as DslExchange
from src.backend.dsl.engine.exchange import ExchangeStatus as DslExchangeStatus
from src.backend.dsl.engine.exchange import Message as DslMessage
from src.backend.infrastructure.workflow.executor.sequential_mixin import _run_processor


@pytest.mark.unit
def test_dsl_exchange_reexports_canonical_core_models() -> None:
    """Старый DSL-публичный импорт остаётся совместимым."""
    assert DslExchange is CoreExchange
    assert DslExchangeStatus is CoreExchangeStatus
    assert DslMessage is CoreMessage


@pytest.mark.unit
def test_clone_preserves_tenant_and_principal() -> None:
    """``clone()`` сохраняет tenant/principal (иначе — чужой scope).

    Регрессия: ``clone()`` копировал только ``route_id`` и
    ``correlation_id`` — capability-гейт процессора брал tenant из
    ``exchange.meta.tenant_id`` и без него уходил в платформенный scope
    ``_system``, а tenant-aware процессоры агентов — в ``"unknown"``.
    """
    exchange = CoreExchange[dict[str, Any]]()
    exchange.meta.route_id = "route-1"
    exchange.meta.tenant_id = "tenant-a"
    exchange.meta.principal = "user-1"
    exchange.meta.source = "http"
    exchange.meta.protocol = "rest"
    exchange.meta.protocol_attrs = {"path": "/v1/orders"}
    exchange.in_message.data_kind = DataKind.BATCH
    exchange.in_message.watermark = 123.0

    cloned = exchange.clone()

    assert cloned is not exchange
    assert cloned.meta.exchange_id != exchange.meta.exchange_id
    assert cloned.meta.route_id == "route-1"
    assert cloned.meta.tenant_id == "tenant-a"
    assert cloned.meta.principal == "user-1"
    assert cloned.meta.source == "http"
    assert cloned.meta.protocol == "rest"
    assert cloned.meta.protocol_attrs == {"path": "/v1/orders"}
    assert cloned.in_message.data_kind is DataKind.BATCH
    assert cloned.in_message.watermark == 123.0
    assert cloned.status is CoreExchangeStatus.processing


@pytest.mark.unit
@pytest.mark.asyncio
async def test_sequential_processor_receives_core_exchange() -> None:
    """Sequential executor оборачивает body в core-Exchange."""
    received: dict[str, Any] = {}

    async def _processor(
        exchange: CoreExchange[dict[str, Any]],
    ) -> CoreExchange[dict[str, Any]]:
        received["exchange"] = exchange
        return exchange

    with patch(
        "src.backend.infrastructure.workflow.executor.sequential_mixin."
        "_is_exchange_wrapping_enabled",
        return_value=True,
    ):
        result = await _run_processor(
            _processor, {"value": 42}, timeout=1.0, idempotency_key="idem-1"
        )

    exchange = received["exchange"]
    assert isinstance(exchange, CoreExchange)
    assert exchange.in_message.body == {"value": 42}
    assert exchange.get_property("idempotency_key") == "idem-1"
    assert result == {"value": 42}
