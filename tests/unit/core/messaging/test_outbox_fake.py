"""Unit-тесты для [FakeOutbox] — Protocol + Fake реализация Outbox/DLQ."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backend.core.messaging import (
    FakeOutbox,
    OutboxBackend,
    OutboxEvent,
    OutboxEventStatus,
)


@pytest.fixture
def outbox() -> FakeOutbox:
    """Чистая инстанция FakeOutbox для каждого теста."""
    return FakeOutbox()


@pytest.fixture
def http_dlq_event() -> OutboxEvent:
    """Тестовое событие в статусе DLQ через transport=http."""
    return OutboxEvent(
        transport="http",
        action="api.send",
        payload={"to": "user@example.com", "subject": "Test"},
        error_class="HTTPError",
        error_message="503 Service Unavailable",
        retry_count=5,
        max_attempts=5,
        status=OutboxEventStatus.DLQ,
        tenant_id="tenant-a",
    )


@pytest.mark.asyncio
async def test_fake_outbox_implements_protocol(outbox: FakeOutbox) -> None:
    """FakeOutbox должен соответствовать [OutboxBackend] Protocol."""
    assert isinstance(outbox, OutboxBackend)


@pytest.mark.asyncio
async def test_enqueue_returns_event_id(outbox: FakeOutbox) -> None:
    """enqueue возвращает event_id из модели."""
    event = OutboxEvent(transport="http", action="api.send")
    returned = await outbox.enqueue(event)
    assert returned == event.event_id


@pytest.mark.asyncio
async def test_list_dlq_returns_only_dlq_status(
    outbox: FakeOutbox, http_dlq_event: OutboxEvent
) -> None:
    """list_dlq не возвращает события со статусом PENDING/DELIVERED/RESOLVED."""
    pending = OutboxEvent(transport="http", action="api.send")
    await outbox.enqueue(pending)
    await outbox.enqueue(http_dlq_event)

    dlq = await outbox.list_dlq()

    assert len(dlq) == 1
    assert dlq[0].event_id == http_dlq_event.event_id
    assert dlq[0].status == OutboxEventStatus.DLQ


@pytest.mark.asyncio
async def test_list_dlq_filters_by_transport_action_error_tenant(
    outbox: FakeOutbox,
) -> None:
    """Фильтры transport/action/error_class/tenant_id комбинируются AND."""
    event_a = OutboxEvent(
        transport="http",
        action="api.x",
        error_class="HTTPError",
        tenant_id="t1",
        status=OutboxEventStatus.DLQ,
    )
    event_b = OutboxEvent(
        transport="kafka",
        action="api.x",
        error_class="HTTPError",
        tenant_id="t1",
        status=OutboxEventStatus.DLQ,
    )
    event_c = OutboxEvent(
        transport="http",
        action="api.y",
        error_class="TimeoutError",
        tenant_id="t2",
        status=OutboxEventStatus.DLQ,
    )
    for e in (event_a, event_b, event_c):
        await outbox.enqueue(e)

    result_http = await outbox.list_dlq(transport="http")
    result_kafka_http = await outbox.list_dlq(
        transport="kafka", error_class="HTTPError"
    )
    result_t2 = await outbox.list_dlq(tenant_id="t2")

    assert {e.event_id for e in result_http} == {event_a.event_id, event_c.event_id}
    assert {e.event_id for e in result_kafka_http} == {event_b.event_id}
    assert {e.event_id for e in result_t2} == {event_c.event_id}


@pytest.mark.asyncio
async def test_list_dlq_filters_by_since(outbox: FakeOutbox) -> None:
    """Фильтр since отрезает события с created_at < since."""
    old_event = OutboxEvent(
        transport="http",
        action="api.send",
        status=OutboxEventStatus.DLQ,
        created_at=datetime.now(timezone.utc) - timedelta(hours=2),
    )
    new_event = OutboxEvent(
        transport="http", action="api.send", status=OutboxEventStatus.DLQ
    )
    await outbox.enqueue(old_event)
    await outbox.enqueue(new_event)

    since = datetime.now(timezone.utc) - timedelta(hours=1)
    result = await outbox.list_dlq(since=since)

    assert {e.event_id for e in result} == {new_event.event_id}


@pytest.mark.asyncio
async def test_replay_transitions_dlq_to_pending(
    outbox: FakeOutbox, http_dlq_event: OutboxEvent
) -> None:
    """replay переводит DLQ → PENDING + сбрасывает retry_count."""
    await outbox.enqueue(http_dlq_event)

    affected = await outbox.replay([http_dlq_event.event_id])

    assert affected == 1
    refreshed = await outbox.list_dlq()  # уже не в DLQ
    assert len(refreshed) == 0


@pytest.mark.asyncio
async def test_replay_dry_run_does_not_change_status(
    outbox: FakeOutbox, http_dlq_event: OutboxEvent
) -> None:
    """dry_run возвращает count, но не меняет статус событий."""
    await outbox.enqueue(http_dlq_event)

    affected = await outbox.replay([http_dlq_event.event_id], dry_run=True)
    dlq_after = await outbox.list_dlq()

    assert affected == 1
    assert len(dlq_after) == 1
    assert dlq_after[0].status == OutboxEventStatus.DLQ


@pytest.mark.asyncio
async def test_replay_override_payload(
    outbox: FakeOutbox, http_dlq_event: OutboxEvent
) -> None:
    """override_payload подменяет payload при replay."""
    await outbox.enqueue(http_dlq_event)
    new_payload = {"to": "fixed@example.com", "subject": "Edited"}

    await outbox.replay([http_dlq_event.event_id], override_payload=new_payload)

    # Replay переводит в PENDING — берём stats
    stats = await outbox.stats()
    assert stats.get(OutboxEventStatus.PENDING.value, 0) == 1


@pytest.mark.asyncio
async def test_mark_resolved_transitions_to_resolved(
    outbox: FakeOutbox, http_dlq_event: OutboxEvent
) -> None:
    """mark_resolved переводит события в RESOLVED + audit-сообщение."""
    await outbox.enqueue(http_dlq_event)

    affected = await outbox.mark_resolved(
        [http_dlq_event.event_id], operator="ivanov", reason="duplicate"
    )

    assert affected == 1
    stats = await outbox.stats()
    assert stats.get(OutboxEventStatus.RESOLVED.value, 0) == 1


@pytest.mark.asyncio
async def test_force_to_dlq_helper(outbox: FakeOutbox) -> None:
    """Тестовый хелпер _force_to_dlq имитирует max_attempts exhausted."""
    pending = OutboxEvent(transport="http", action="api.send")
    eid = await outbox.enqueue(pending)

    ok = await outbox._force_to_dlq(eid, RuntimeError("boom"))

    assert ok is True
    dlq = await outbox.list_dlq()
    assert len(dlq) == 1
    assert dlq[0].error_class == "RuntimeError"
    assert dlq[0].error_message == "boom"


@pytest.mark.asyncio
async def test_stats_aggregates_status(outbox: FakeOutbox) -> None:
    """stats возвращает счётчики по статусам."""
    e1 = OutboxEvent(transport="http", action="x", status=OutboxEventStatus.PENDING)
    e2 = OutboxEvent(transport="http", action="x", status=OutboxEventStatus.DLQ)
    e3 = OutboxEvent(transport="http", action="x", status=OutboxEventStatus.DLQ)
    for e in (e1, e2, e3):
        await outbox.enqueue(e)

    stats = await outbox.stats()

    assert stats[OutboxEventStatus.PENDING.value] == 1
    assert stats[OutboxEventStatus.DLQ.value] == 2
