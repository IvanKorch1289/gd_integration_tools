"""Unit-тесты DLQEnvelope scaffold (Sprint 8 K2 W3)."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.backend.infrastructure.messaging.dlq import (
    DLQEnvelope,
    DLQReason,
    DLQWriter,
)


def test_envelope_minimal_creation() -> None:
    """DLQEnvelope создаётся с минимальным набором обязательных полей."""
    env = DLQEnvelope(
        transport="http",
        error_class="httpx.ConnectTimeout",
        error_message="timeout to backend",
    )

    assert env.dlq_id
    assert env.transport == "http"
    assert env.reason is DLQReason.UNEXPECTED
    assert env.retry_count == 0
    assert env.metadata == {}
    assert env.first_failed_at.tzinfo == timezone.utc


def test_envelope_with_all_fields() -> None:
    """Все необязательные поля корректно проставляются."""
    now = datetime.now(timezone.utc)
    env = DLQEnvelope(
        transport="grpc",
        trace_id="trace-123",
        tenant_id="tenant-x",
        route_id="route.foo",
        original_payload={"k": "v"},
        error_class="grpc.RpcError",
        error_message="DEADLINE_EXCEEDED",
        reason=DLQReason.TIMEOUT,
        retry_count=3,
        first_failed_at=now,
        last_failed_at=now,
        metadata={"upstream": "grpc://backend:50051"},
    )

    assert env.transport == "grpc"
    assert env.reason is DLQReason.TIMEOUT
    assert env.retry_count == 3
    assert env.metadata["upstream"] == "grpc://backend:50051"


def test_dlq_reason_values() -> None:
    """Все DLQReason значения совпадают со значимыми именами."""
    assert DLQReason.TIMEOUT.value == "timeout"
    assert DLQReason.RETRIES_EXHAUSTED.value == "retries_exhausted"
    assert DLQReason.VALIDATION_FAILED.value == "validation_failed"
    assert DLQReason.CAPABILITY_DENIED.value == "capability_denied"
    assert DLQReason.WAF_BLOCKED.value == "waf_blocked"
    assert DLQReason.UNEXPECTED.value == "unexpected"


def test_dlqwriter_protocol_runtime_checkable() -> None:
    """DLQWriter — runtime_checkable Protocol, поддерживает isinstance."""

    class InMemoryWriter:
        async def write(self, envelope: DLQEnvelope) -> None:
            pass

    class BrokenWriter:
        async def push(self, x: DLQEnvelope) -> None:
            pass

    assert isinstance(InMemoryWriter(), DLQWriter)
    assert not isinstance(BrokenWriter(), DLQWriter)


@pytest.mark.asyncio
async def test_dlqwriter_in_memory_smoke() -> None:
    """Smoke: InMemoryWriter принимает envelope без exception."""

    class InMemoryWriter:
        def __init__(self) -> None:
            self.records: list[DLQEnvelope] = []

        async def write(self, envelope: DLQEnvelope) -> None:
            self.records.append(envelope)

    writer = InMemoryWriter()
    env = DLQEnvelope(
        transport="webhook",
        error_class="WebhookSignatureError",
        error_message="HMAC mismatch",
        reason=DLQReason.VALIDATION_FAILED,
    )
    await writer.write(env)
    assert len(writer.records) == 1
    assert writer.records[0].transport == "webhook"
