"""Дополнительные регрессии remaining services contract adapters."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.capabilities.facade import CapabilityFacade
from src.backend.services.observability.facade import ObservabilityFacade
from src.backend.services.security.facade import SecurityFacade
from src.backend.services.workflows.hitl_signal_store_redis import RedisHitlSignalStore


@pytest.mark.unit
def test_observability_log_event_does_not_swallow_body_error() -> None:
    with patch(
        "src.backend.core.observability.logging_helpers.log_audit_event_lite",
    ) as log_event, pytest.raises(ValueError, match="body failed"):
        with ObservabilityFacade().log_event("orders.failed", order_id="42"):
            raise ValueError("body failed")

    log_event.assert_called_once()


@pytest.mark.unit
def test_capability_subset_adapter_returns_true_after_void_contract() -> None:
    assert CapabilityFacade().check_subsets(
        route="route-1", route_caps=[], plugin_caps_by_name={},
    ) is True


@pytest.mark.unit
@pytest.mark.asyncio
async def test_security_secret_uses_registered_backend_contract() -> None:
    backend = MagicMock()
    backend.get_secret = AsyncMock(return_value="value")

    with patch("src.backend.core.svcs_registry.get_service", return_value=backend):
        result = await SecurityFacade().get_secret("service.password")

    assert result == "value"
    backend.get_secret.assert_awaited_once_with("service.password")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_hitl_transaction_does_not_retry_non_watch_errors() -> None:
    pipeline = MagicMock()
    pipeline.__aenter__ = AsyncMock(return_value=pipeline)
    pipeline.__aexit__ = AsyncMock(return_value=None)
    pipeline.watch = AsyncMock(side_effect=ConnectionError("redis down"))
    client = MagicMock()
    client.pipeline.return_value = pipeline
    store = RedisHitlSignalStore(redis_client=client)

    with pytest.raises(ConnectionError, match="redis down"):
        await store._mark_resolved_transactional(
            client,
            "signal-1",
            action="approve",
            resolved_by="operator-1",
        )
