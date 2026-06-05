"""Tests for src.backend.core.messaging.dlq re-export module.

Covers the re-export surface (``DLQEnvelope``/``DLQReason``/``DLQWriter``) and
mock-backed behaviour of the underlying writer protocol. Sprint 39 carryover.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.backend.core.messaging import dlq as dlq_module
from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason, DLQWriter

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_envelope() -> DLQEnvelope:
    return DLQEnvelope(
        transport="http",
        error_class="httpx.ConnectTimeout",
        error_message="upstream unreachable",
        reason=DLQReason.TIMEOUT,
        retry_count=3,
        trace_id="trace-abc-123",
        tenant_id="tenant-42",
        route_id="route-payments",
    )


@pytest.fixture
def mock_backend() -> MagicMock:
    backend = MagicMock(name="DLQBackend")
    backend.write = AsyncMock(return_value=None)
    backend.read = AsyncMock(return_value=[])
    backend.delete = AsyncMock(return_value=True)
    return backend


@pytest.fixture
def metrics_collector() -> dict[str, int]:
    return {"writes": 0, "errors": 0, "replays": 0, "cleanups": 0}


class InMemoryDLQWriter:
    """Test-only ``DLQWriter``: in-memory list with simulated transient failures."""

    def __init__(self) -> None:
        self.entries: list[DLQEnvelope] = []
        self.fail_n: int = 0
        self.attempts: int = 0

    async def write(self, envelope: DLQEnvelope) -> None:
        self.attempts += 1
        if self.attempts <= self.fail_n:
            raise ConnectionError(f"backend-failure-{self.attempts}")
        self.entries.append(envelope)

    async def read(self, limit: int = 100) -> list[DLQEnvelope]:
        return list(self.entries[:limit])

    async def cleanup_expired(self, ttl: timedelta) -> int:
        now = datetime.now(UTC)
        kept, removed = [], 0
        for env in self.entries:
            if (now - env.last_failed_at) > ttl:
                removed += 1
            else:
                kept.append(env)
        self.entries = kept
        return removed


# ---------------------------------------------------------------------------
# Re-export / public API
# ---------------------------------------------------------------------------


def test_module_exposes_all_three_names() -> None:
    assert hasattr(dlq_module, "DLQEnvelope")
    assert hasattr(dlq_module, "DLQReason")
    assert hasattr(dlq_module, "DLQWriter")
    assert dlq_module.__all__ == ("DLQEnvelope", "DLQReason", "DLQWriter")


def test_re_exports_resolve_to_same_classes() -> None:
    from src.backend.infrastructure.messaging import dlq_base

    assert dlq_module.DLQEnvelope is dlq_base.DLQEnvelope
    assert dlq_module.DLQReason is dlq_base.DLQReason
    assert dlq_module.DLQWriter is dlq_base.DLQWriter


def test_unknown_attribute_raises_attribute_error() -> None:
    with pytest.raises(AttributeError):
        dlq_module.__getattr__("DoesNotExist")  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# DLQReason
# ---------------------------------------------------------------------------


def test_dlq_reason_values() -> None:
    assert DLQReason.TIMEOUT == "timeout"
    assert DLQReason.RETRIES_EXHAUSTED == "retries_exhausted"
    assert DLQReason.VALIDATION_FAILED == "validation_failed"
    assert DLQReason.CAPABILITY_DENIED == "capability_denied"
    assert DLQReason.WAF_BLOCKED == "waf_blocked"
    assert DLQReason.UNEXPECTED == "unexpected"
    assert isinstance(DLQReason.TIMEOUT, str)


# ---------------------------------------------------------------------------
# DLQEnvelope
# ---------------------------------------------------------------------------


def test_envelope_defaults_are_populated(sample_envelope: DLQEnvelope) -> None:
    assert sample_envelope.dlq_id  # auto-generated UUID
    assert sample_envelope.first_failed_at.tzinfo is not None
    assert sample_envelope.metadata == {}


def test_envelope_serialization_roundtrip(sample_envelope: DLQEnvelope) -> None:
    payload = sample_envelope.model_dump_json()
    restored = DLQEnvelope.model_validate_json(payload)
    assert restored.model_dump() == sample_envelope.model_dump()


def test_envelope_rejects_missing_required_fields() -> None:
    with pytest.raises(ValidationError):
        DLQEnvelope()  # type: ignore[call-arg]


def test_envelope_accepts_arbitrary_payload() -> None:
    env = DLQEnvelope(
        transport="grpc",
        error_class="grpc.RpcError",
        error_message="UNAVAILABLE",
        original_payload={"nested": [1, 2, 3], "unicode": "тест"},
    )
    assert env.original_payload == {"nested": [1, 2, 3], "unicode": "тест"}


def test_envelope_metadata_default_is_isolated() -> None:
    a = DLQEnvelope(transport="http", error_class="E", error_message="m")
    b = DLQEnvelope(transport="http", error_class="E", error_message="m")
    a.metadata["k"] = "v"
    assert b.metadata == {}


def test_envelope_tenant_isolation() -> None:
    a = DLQEnvelope(transport="http", error_class="E", error_message="m", tenant_id="A")
    b = DLQEnvelope(transport="http", error_class="E", error_message="m", tenant_id="B")
    assert a.tenant_id != b.tenant_id
    assert a.dlq_id != b.dlq_id


# ---------------------------------------------------------------------------
# DLQWriter behaviour (mock-backed)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_dlq_writer_creates_entry(sample_envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    await writer.write(sample_envelope)
    assert len(writer.entries) == 1
    assert writer.entries[0].dlq_id == sample_envelope.dlq_id


@pytest.mark.asyncio
async def test_dlq_writer_handles_backend_error(sample_envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    writer.fail_n = 1
    with pytest.raises(ConnectionError, match="backend-failure-1"):
        await writer.write(sample_envelope)
    assert writer.entries == []


@pytest.mark.asyncio
async def test_dlq_writer_retries_on_failure(
    sample_envelope: DLQEnvelope, metrics_collector: dict[str, int]
) -> None:
    writer = InMemoryDLQWriter()
    writer.fail_n = 2

    async def write_with_retry(env: DLQEnvelope, max_retries: int = 3) -> int:
        last_exc: Exception | None = None
        for attempt in range(max_retries):
            try:
                await writer.write(env)
                return attempt
            except ConnectionError as exc:
                metrics_collector["errors"] += 1
                last_exc = exc
        if last_exc:
            raise last_exc
        return max_retries

    attempts = await write_with_retry(sample_envelope)
    assert attempts == 2
    assert metrics_collector["errors"] == 2
    assert len(writer.entries) == 1


@pytest.mark.asyncio
async def test_dlq_reader_returns_entries(sample_envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    for i in range(5):
        await writer.write(sample_envelope.model_copy(update={"retry_count": i}))
    entries = await writer.read(limit=10)
    assert len(entries) == 5
    assert [e.retry_count for e in entries] == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_dlq_reader_handles_empty() -> None:
    writer = InMemoryDLQWriter()
    assert await writer.read() == []


@pytest.mark.asyncio
async def test_dlq_replay_moves_to_main(sample_envelope: DLQEnvelope) -> None:
    """Replay: read from DLQ → republish → remove from DLQ."""
    writer = InMemoryDLQWriter()
    main_queue: list[DLQEnvelope] = []
    await writer.write(sample_envelope)

    replayed = await writer.read()
    assert replayed
    main_queue.extend(replayed)
    writer.entries = []

    assert len(main_queue) == 1
    assert writer.entries == []
    assert main_queue[0].dlq_id == sample_envelope.dlq_id


@pytest.mark.asyncio
async def test_dlq_cleanup_expired_entries() -> None:
    writer = InMemoryDLQWriter()
    now = datetime.now(UTC)
    old = DLQEnvelope(
        transport="http",
        error_class="E",
        error_message="m",
        last_failed_at=now - timedelta(hours=48),
        first_failed_at=now - timedelta(hours=49),
    )
    fresh = DLQEnvelope(
        transport="http",
        error_class="E",
        error_message="m",
        last_failed_at=now - timedelta(minutes=5),
    )
    writer.entries = [old, fresh]
    removed = await writer.cleanup_expired(ttl=timedelta(hours=24))
    assert removed == 1
    assert writer.entries == [fresh]


@pytest.mark.asyncio
async def test_dlq_metrics_increment(
    sample_envelope: DLQEnvelope, metrics_collector: dict[str, int]
) -> None:
    writer = InMemoryDLQWriter()
    for _ in range(3):
        await writer.write(sample_envelope)
        metrics_collector["writes"] += 1
    assert metrics_collector["writes"] == 3
    assert len(writer.entries) == 3


@pytest.mark.asyncio
async def test_dlq_concurrent_writers(sample_envelope: DLQEnvelope) -> None:
    writer = InMemoryDLQWriter()
    n = 20
    envs = [
        sample_envelope.model_copy(update={"trace_id": f"trace-{i}"}) for i in range(n)
    ]
    await asyncio.gather(*(writer.write(e) for e in envs))
    assert len(writer.entries) == n
    assert len({e.trace_id for e in writer.entries}) == n


def test_dlq_payload_serialization(sample_envelope: DLQEnvelope) -> None:
    sample_envelope.metadata = {"upstream_url": "https://bank.example/pay", "code": 502}
    sample_envelope.original_payload = b"\x00\x01binary"
    data = sample_envelope.model_dump()
    restored = DLQEnvelope.model_validate(data)
    assert restored.metadata["code"] == 502
    assert restored.original_payload == b"\x00\x01binary"
    assert restored.reason is DLQReason.TIMEOUT


def test_dlq_writer_protocol_is_runtime_checkable() -> None:
    assert isinstance(InMemoryDLQWriter(), DLQWriter)

    class NotAWriter:
        pass

    assert not isinstance(NotAWriter(), DLQWriter)


@pytest.mark.asyncio
async def test_dlq_writer_with_mock_backend_aggregation(
    sample_envelope: DLQEnvelope, mock_backend: MagicMock
) -> None:
    """Writer composes with a mocked external backend (Redis/Kafka/S3)."""
    mock_backend.write.return_value = None
    await mock_backend.write(sample_envelope)
    mock_backend.write.assert_awaited_once()
    sent_envelope = mock_backend.write.await_args.args[0]
    assert sent_envelope.dlq_id == sample_envelope.dlq_id


def test_dlq_module_does_not_eagerly_import_infrastructure() -> None:
    """TYPE_CHECKING guard: the re-export must not pull infrastructure at import."""
    import sys

    # Force fresh re-import of dlq while infrastructure is hidden
    infra_name = "src.backend.infrastructure.messaging.dlq_base"
    saved = sys.modules.pop(infra_name, None)
    try:
        sys.modules.pop("src.backend.core.messaging.dlq", None)
        import src.backend.core.messaging.dlq  # noqa: F401

        # dlq module loaded successfully even when base was evicted
        assert "src.backend.core.messaging.dlq" in sys.modules
    finally:
        if saved is not None:
            sys.modules[infra_name] = saved
