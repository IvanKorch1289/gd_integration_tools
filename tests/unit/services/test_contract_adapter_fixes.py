"""Regression tests for services contract adapters fixed by the mypy sweep."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.services.ai.llm import tgi_batch_client
from src.backend.services.ai.llm.tgi_batch_client import TgiBatchClient
from src.backend.services.ai.memory.langmem_service import LangMemService
from src.backend.services.observability.facade import ObservabilityFacade
from src.backend.services.secrets.facade import SecretsFacade
from src.backend.services.workflows.hitl_pubsub import publish_hitl_resolved

pytestmark = pytest.mark.unit


class _Metric:
    def __init__(self) -> None:
        self.labels = MagicMock(return_value=self)
        self.inc = MagicMock()


@pytest.mark.asyncio
async def test_observability_records_counter_through_registry() -> None:
    metric = _Metric()
    registry = MagicMock()
    registry.counter.return_value = metric

    with patch("src.backend.services.observability.facade.metrics_registry", registry):
        await ObservabilityFacade(plugin="orders").record_metric(
            "orders_processed", 2.0, tags={"status": "ok"}
        )

    registry.counter.assert_called_once_with(
        "orders_processed",
        "Observability metric orders_processed",
        labels=("status", "plugin"),
    )
    metric.labels.assert_called_once_with(status="ok", plugin="orders")
    metric.inc.assert_called_once_with(2.0)


def test_observability_log_event_uses_logging_helper_as_function() -> None:
    with patch(
        "src.backend.core.observability.logging_helpers.log_audit_event_lite"
    ) as log_event:
        with ObservabilityFacade().log_event("order.created", order_id="42"):
            pass

    log_event.assert_called_once()


@pytest.mark.asyncio
async def test_secrets_facade_uses_async_backend_contract() -> None:
    backend = AsyncMock()
    backend.get_secret.return_value = "value"
    facade = SecretsFacade(backend=backend)

    assert await facade.get_secret("key") == "value"
    await facade.set_secret("key", "new-value")

    backend.get_secret.assert_awaited_once_with("key")
    backend.set_secret.assert_awaited_once_with("key", "new-value")


class _Response:
    def json(self) -> dict[str, object]:
        return {"generated_text": 123}

    def raise_for_status(self) -> None:
        return None


class _Breaker:
    @asynccontextmanager
    async def guard(self):
        yield


@pytest.mark.asyncio
async def test_tgi_completion_normalizes_generated_text_to_string() -> None:
    client = AsyncMock()
    client.post.return_value = _Response()

    with patch.object(tgi_batch_client, "_get_tgi_breaker", return_value=_Breaker()):
        result = await TgiBatchClient(
            base_url="http://tgi", http_client=client
        )._single_completion("prompt", max_tokens=8, temperature=0.0)

    assert result == "123"


@pytest.mark.asyncio
async def test_langmem_stats_counts_kinds_across_agent_buckets() -> None:
    service = LangMemService(enabled=True, use_inmemory=True)
    await service.remember_episode("agent-a", "episode", {})
    await service.remember_fact("agent-a", "fact", [0.1])
    await service.remember_procedure("agent-b", "procedure", ["step"])

    assert await service.stats() == {
        "episodic_count": 1,
        "semantic_count": 2,
        "procedural_count": 1,
        "total": 4,
    }


@pytest.mark.asyncio
async def test_hitl_pubsub_resolves_raw_queue_client_before_publish() -> None:
    raw = AsyncMock()
    raw.publish.return_value = 2
    wrapper = MagicMock()
    wrapper.get_client = AsyncMock(return_value=raw)

    with patch(
        "src.backend.infrastructure.clients.storage.redis.get_redis_client",
        return_value=wrapper,
    ):
        subscribers = await publish_hitl_resolved(
            signal_id="sig-1",
            workflow_id="wf-1",
            tenant_id="tenant-1",
            action="approve",
            resolved_by="operator",
        )

    assert subscribers == 2
    wrapper.get_client.assert_awaited_once_with("queue")
    raw.publish.assert_awaited_once()
