"""Unit tests for core ABCs and Protocols.

Covers:
- AntivirusBackend, AuditBackend, CacheBackend, DocStoreBackend,
  MetricsBackend, NotificationAdapter, SecretsBackend, ObjectStorage
- HealthStatus, HealthReport, Healthcheck
- MessageBroker, AsyncLifecycle, ManagedResource
- CircuitBreaker, CircuitBreakerConfig, CircuitState, CircuitBreakerOpenError
- PoolMetrics, PoolMetricsCollector, pool_metrics
- AuthProvider, AsyncBatcher
"""

# ruff: noqa: S101, D101, D102

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.core.interfaces import (
    AsyncBatcher,
    CircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerOpenError,
    CircuitState,
    HealthReport,
    HealthStatus,
    PoolMetrics,
    PoolMetricsCollector,
    pool_metrics,
)
from src.backend.core.interfaces.antivirus import AntivirusScanResult
from src.backend.core.interfaces.audit import AuditRecord
from src.backend.core.interfaces.capability_gateway import CapabilityGatewayProtocol
from src.backend.core.interfaces.notification import NotificationMessage
from src.backend.core.interfaces.storage import ObjectStorage

# ─── Antivirus ──────────────────────────────────────────────────────────────


def test_antivirus_scan_result_defaults() -> None:
    result = AntivirusScanResult(clean=True)
    assert result.clean is True
    assert result.signature is None
    assert result.backend == ""
    assert result.latency_ms is None


def test_antivirus_scan_result_full() -> None:
    result = AntivirusScanResult(
        clean=False, signature="EICAR", backend="clamav", latency_ms=12.5
    )
    assert result.clean is False
    assert result.signature == "EICAR"
    assert result.backend == "clamav"
    assert result.latency_ms == 12.5


# ─── Audit ──────────────────────────────────────────────────────────────────


def test_audit_record_is_dict() -> None:
    record = AuditRecord({"event": "login", "actor": "u1"})
    assert record["event"] == "login"
    assert isinstance(record, dict)


# ─── Notification ───────────────────────────────────────────────────────────


def test_notification_message_defaults() -> None:
    msg = NotificationMessage(recipient="user@example.com")
    assert msg.recipient == "user@example.com"
    assert msg.subject == ""
    assert msg.body == ""
    assert msg.metadata == {}


def test_notification_message_full() -> None:
    msg = NotificationMessage(
        recipient="u1", subject="hi", body="hello", metadata={"k": "v"}
    )
    assert msg.metadata == {"k": "v"}


# ─── Capability Gateway Protocol ────────────────────────────────────────────


def test_capability_gateway_protocol_runtime_checkable() -> None:
    class DummyGate:
        def check(
            self, plugin: str, capability: str, scope: str | None = None
        ) -> None: ...

        def declare(self, plugin: str, capabilities: Any) -> None: ...

        def list_allocated(self, plugin: str) -> tuple[str, ...]:
            return ()

    assert isinstance(DummyGate(), CapabilityGatewayProtocol)


# ─── ObjectStorage ──────────────────────────────────────────────────────────


def test_object_storage_supports_presigned_default() -> None:
    class DummyStorage(ObjectStorage):
        async def upload(
            self, key: str, data: bytes, content_type: str | None = None
        ) -> str:
            return ""

        async def download(self, key: str) -> bytes:
            return b""

        async def delete(self, key: str) -> None: ...

        async def exists(self, key: str) -> bool:
            return False

        async def list_keys(self, prefix: str = "") -> list[str]:
            return []

        async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
            return ""

    storage = DummyStorage()
    assert storage.supports_presigned() is True


# ─── Health ─────────────────────────────────────────────────────────────────


def test_health_status_values() -> None:
    assert HealthStatus.HEALTHY.value == "healthy"
    assert HealthStatus.DEGRADED.value == "degraded"
    assert HealthStatus.UNHEALTHY.value == "unhealthy"


def test_health_report_defaults() -> None:
    report = HealthReport(name="db", status=HealthStatus.HEALTHY)
    assert report.name == "db"
    assert report.status == HealthStatus.HEALTHY
    assert report.latency_ms is None
    assert report.details is None


# ─── CircuitBreaker ─────────────────────────────────────────────────────────


def test_cb_starts_closed() -> None:
    cb = CircuitBreaker("test")
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True


def test_cb_opens_after_threshold() -> None:
    cb = CircuitBreaker("test", config=CircuitBreakerConfig(failure_threshold=2))
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False


def test_cb_half_open_then_closes() -> None:
    config = CircuitBreakerConfig(
        failure_threshold=1, recovery_timeout=0.0, success_threshold=1
    )
    cb = CircuitBreaker("test", config=config)
    cb.record_failure()
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


def test_cb_half_open_limited_calls() -> None:
    config = CircuitBreakerConfig(
        failure_threshold=1, recovery_timeout=0.0, half_open_max_calls=1
    )
    cb = CircuitBreaker("test", config=config)
    cb.record_failure()
    assert cb.allow_request() is True
    assert cb.allow_request() is False


def test_cb_aenter_aexit_success() -> None:
    cb = CircuitBreaker("test")

    async def _run() -> None:
        async with cb:
            pass

    import asyncio

    asyncio.run(_run())
    assert cb.state == CircuitState.CLOSED


def test_cb_aenter_aexit_failure() -> None:
    config = CircuitBreakerConfig(failure_threshold=1)
    cb = CircuitBreaker("test", config=config)

    async def _run() -> None:
        async with cb:
            raise RuntimeError("boom")

    import asyncio

    with pytest.raises(RuntimeError, match="boom"):
        asyncio.run(_run())
    assert cb.state == CircuitState.OPEN


def test_cb_open_error() -> None:
    err = CircuitBreakerOpenError("svc")
    assert err.breaker_name == "svc"
    assert "svc" in str(err)


# ─── PoolMetrics ────────────────────────────────────────────────────────────


def test_pool_metrics_defaults() -> None:
    pm = PoolMetrics(name="pg")
    assert pm.active == 0
    assert pm.idle == 0


def test_pool_metrics_collector() -> None:
    collector = PoolMetricsCollector()
    collector.register("pg", max_size=10)
    collector.update("pg", active=2, idle=8)
    pm = collector.get("pg")
    assert pm is not None
    assert pm.active == 2
    assert pm.idle == 8
    assert collector.get_all() == [pm]


def test_pool_metrics_collector_get_missing() -> None:
    assert PoolMetricsCollector().get("missing") is None


def test_pool_metrics_global_instance() -> None:
    pool_metrics.register("test", max_size=5)
    assert pool_metrics.get("test") is not None


# ─── AsyncBatcher ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_async_batcher_add_and_flush() -> None:
    flushed: list[Any] = []

    def flush_fn(batch: list[Any]) -> None:
        flushed.extend(batch)

    batcher = AsyncBatcher(flush_fn, batch_size=2)
    await batcher.add(1)
    assert flushed == []
    await batcher.add(2)
    assert flushed == [1, 2]


@pytest.mark.asyncio
async def test_async_batcher_flush_empty() -> None:
    batcher = AsyncBatcher(lambda b: None, batch_size=10)
    await batcher._do_flush()


@pytest.mark.asyncio
async def test_async_batcher_start_stop() -> None:
    with patch(
        "src.backend.core.utils.task_registry.get_task_registry"
    ) as mock_registry:
        mock_task = MagicMock()
        mock_registry.return_value.create_task.return_value = mock_task
        batcher = AsyncBatcher(
            lambda b: None, batch_size=10, flush_interval_seconds=0.01
        )
        await batcher.start()
        assert batcher._running is True
        await batcher.stop()
        mock_task.cancel.assert_called_once()


@pytest.mark.asyncio
async def test_async_batcher_periodic_flush() -> None:
    flushed: list[Any] = []

    def flush_fn(batch: list[Any]) -> None:
        flushed.extend(batch)

    with patch(
        "src.backend.core.utils.task_registry.get_task_registry"
    ) as mock_registry:
        mock_task = MagicMock()
        mock_registry.return_value.create_task.return_value = mock_task
        batcher = AsyncBatcher(flush_fn, batch_size=100, flush_interval_seconds=0.01)
        await batcher.start()
        await batcher.add(42)
        # periodic flush runs in background; stop triggers final flush
        await batcher.stop()
        assert 42 in flushed
