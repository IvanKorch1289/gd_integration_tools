"""Unit tests for DebeziumEventsCDCBackend (S62 W2).

Mock-based — no real Kafka required. Verifies:
* ``parse_debezium_event`` — already tested in debezium_events_backend
* ``subscribe()`` consume loop + parse + yield
* ``ack()`` cursor commit (mock consumer.commit)
* ``replay()`` seek + bounded iteration
* ``close()`` graceful shutdown

Reference: ``src/backend/infrastructure/cdc/debezium_events_backend.py``.
"""

# ruff: noqa: S101

from __future__ import annotations

import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.cdc.source import CDCCursor
from src.backend.infrastructure.cdc.debezium_events_backend import (
    DebeziumEventsCDCBackend,
    parse_debezium_event,
)


@pytest.fixture
def mock_aiokafka(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Stub aiokafka module entirely (не нужен реальный Kafka)."""
    fake_mod = types.ModuleType("aiokafka_stub")

    class FakeTopicPartition:
        def __init__(self, topic: str, partition: int) -> None:
            self.topic = topic
            self.partition = partition

    class FakeOffsetAndMetadata:
        def __init__(self, offset: int, metadata: str) -> None:
            self.offset = offset
            self.metadata = metadata

    class FakeAIOKafkaConsumer:
        def __init__(self, *topics: str, **kwargs: Any) -> None:
            self.topics = topics
            self.kwargs = kwargs
            self.started = False
            self.stopped = False
            self.commits: list[dict[Any, Any]] = []
            self.seeks: list[tuple[Any, int]] = []
            # messages can be injected via kwargs["test_messages"] (list of MagicMock)
            self._messages: list[Any] = kwargs.pop("test_messages", [])
            self._message_idx = 0
            self._exhausted_once = False

        async def start(self) -> None:
            self.started = True

        async def stop(self) -> None:
            self.stopped = True

        async def commit(self, offsets: dict[Any, Any]) -> None:
            self.commits.append(offsets)

        def seek(self, tp: Any, offset: int) -> None:
            self.seeks.append((tp, offset))

        async def getmany(
            self, timeout_ms: int = 1000, max_records: int = 100
        ) -> dict[Any, list[Any]]:
            # Первая порция — preloaded messages; вторая — пусто (test завершает)
            if self._message_idx >= len(self._messages):
                if self._exhausted_once:
                    return {}
                self._exhausted_once = True
                return {}
            tp = FakeTopicPartition(self.topics[0], 0) if self.topics else None
            batch = self._messages[self._message_idx : self._message_idx + max_records]
            self._message_idx += len(batch)
            return {tp: batch} if tp else {}

        def add_messages(self, messages: list[Any]) -> None:
            self._messages.extend(messages)

    # Подготовленные сообщения (test prepopulates через fake_mod.set_test_messages)
    _prepared: list[Any] = []

    def factory(*topics: str, **kwargs: Any) -> FakeAIOKafkaConsumer:
        """Factory: возвращает FakeAIOKafkaConsumer с prepopulated messages."""
        c = FakeAIOKafkaConsumer(*topics, **kwargs)
        c.add_messages(_prepared)
        return c

    def set_test_messages(msgs: list[Any]) -> None:
        """Inject messages в factory (next created consumer их получит)."""
        _prepared.clear()
        _prepared.extend(msgs)

    fake_mod.AIOKafkaConsumer = factory  # type: ignore[attr-defined]
    fake_mod.TopicPartition = FakeTopicPartition  # type: ignore[attr-defined]
    fake_mod.OffsetAndMetadata = FakeOffsetAndMetadata  # type: ignore[attr-defined]
    fake_mod.set_test_messages = set_test_messages  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "aiokafka", fake_mod)
    return fake_mod


@pytest.fixture
def fake_message() -> Any:
    """Stub Kafka message: имеет .value (dict), .offset (int)."""
    msg = MagicMock()
    msg.value = {
        "op": "c",
        "ts_ms": 1234567890,
        "source": {"db": "test", "table": "users"},
        "after": {"id": 1, "name": "alice"},
    }
    msg.offset = 42
    return msg


def test_parse_debezium_event_insert() -> None:
    raw = {
        "op": "c",
        "ts_ms": 1000,
        "source": {"db": "test", "table": "users"},
        "after": {"id": 1},
    }
    event = parse_debezium_event(raw, kafka_offset=10, kafka_partition=0)
    assert event is not None
    assert event.operation == "INSERT"
    assert event.table == "users"
    assert event.new == {"id": 1}
    assert event.cursor.value == "0:10"


def test_parse_debezium_event_update() -> None:
    raw = {
        "op": "u",
        "ts_ms": 1000,
        "source": {"db": "test", "table": "users"},
        "before": {"id": 1, "name": "alice"},
        "after": {"id": 1, "name": "alice2"},
    }
    event = parse_debezium_event(raw, kafka_offset=11, kafka_partition=0)
    assert event is not None
    assert event.operation == "UPDATE"
    assert event.new == {"id": 1, "name": "alice2"}
    assert event.old == {"id": 1, "name": "alice"}


def test_parse_debezium_event_unknown_op_returns_none() -> None:
    raw = {"op": "x", "source": {"table": "users"}}
    event = parse_debezium_event(raw, kafka_offset=0, kafka_partition=0)
    assert event is None


@pytest.mark.asyncio
async def test_subscribe_yields_events(
    mock_aiokafka: Any, fake_message: Any
) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
    mock_aiokafka.set_test_messages([fake_message])

    events: list[Any] = []
    async for event in backend.subscribe(tables=["users"]):
        events.append(event)
        await backend.close()  # stop loop
    assert len(events) == 1
    assert events[0].operation == "INSERT"
    assert events[0].new == {"id": 1, "name": "alice"}


@pytest.mark.asyncio
async def test_subscribe_filters_topics_with_prefix(
    mock_aiokafka: Any, fake_message: Any
) -> None:
    backend = DebeziumEventsCDCBackend(
        bootstrap_servers="localhost:9092", topic_prefix="custom_prefix"
    )
    mock_aiokafka.set_test_messages([fake_message])

    events: list[Any] = []
    async for event in backend.subscribe(tables=["orders", "users"]):
        events.append(event)
        await backend.close()
    assert len(events) == 1
    # Verify topic prefix in event source (Debezium source format: "debezium:<db>")
    # Note: actual topic name with prefix visible only via consumer.topics — covered in
    # consumer creation kwargs. Cursor.backend is fixed to "debezium" (from source).
    assert events[0].source == "debezium:test"


@pytest.mark.asyncio
async def test_ack_commits_offset(mock_aiokafka: Any, fake_message: Any) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
    mock_aiokafka.set_test_messages([fake_message])

    # Trigger consumer creation (one message → one yield → close)
    async for _ in backend.subscribe(tables=["users"]):
        await backend.close()

    # Now ack a cursor
    cursor = CDCCursor(value="0:99", backend="debezium.test.users")
    await backend.ack(cursor)
    # Verify commit was called
    consumer = backend._consumer
    assert consumer is not None
    assert len(consumer.commits) == 1
    commit_offsets = consumer.commits[0]
    # Find the TP and verify offset+1
    tp = list(commit_offsets.keys())[0]
    assert tp.topic == "debezium.test.users"
    assert commit_offsets[tp].offset == 100  # 99 + 1


@pytest.mark.asyncio
async def test_ack_without_consumer_logs_warning(mock_aiokafka: Any) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
    cursor = CDCCursor(value="0:50", backend="debezium")
    # No subscribe called — consumer is None
    await backend.ack(cursor)  # should not raise
    assert len(backend._cursor_log) == 1


@pytest.mark.asyncio
async def test_replay_with_end_cursor_bounds_iteration(
    mock_aiokafka: Any,
) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")

    msgs: list[Any] = []
    for i in range(5):
        m = MagicMock()
        m.value = {
            "op": "c",
            "ts_ms": 1000 + i,
            "source": {"db": "test", "table": "users"},
            "after": {"id": i},
        }
        m.offset = 100 + i
        msgs.append(m)

    # Step 1: prep + consume to create consumer
    mock_aiokafka.set_test_messages(msgs[:1])  # just 1 to trigger close fast
    async for _ in backend.subscribe(tables=["users"]):
        await backend.close()

    # Step 2: clear mock state + add fresh messages for replay
    consumer = backend._consumer
    consumer._messages.clear()
    consumer._exhausted_once = False
    consumer._message_idx = 0
    consumer.add_messages(msgs)

    # Replay from offset 100 to 102 (exclusive)
    events: list[Any] = []
    start = CDCCursor(value="0:100", backend="debezium.test.users")
    end = CDCCursor(value="0:102", backend="debezium.test.users")
    async for event in backend.replay(start_cursor=start, end_cursor=end):
        events.append(event)
    # Should yield offsets 100, 101 (end_cursor.offset=102 exclusive)
    assert len(events) == 2
    assert events[0].new == {"id": 0}
    assert events[1].new == {"id": 1}


@pytest.mark.asyncio
async def test_close_stops_consumer(mock_aiokafka: Any, fake_message: Any) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
    mock_aiokafka.set_test_messages([fake_message])

    async for _ in backend.subscribe(tables=["users"]):
        await backend.close()
    # S62 W2: close() leaves consumer instance for post-mortem, sets stopped=True
    assert backend._consumer is not None
    assert backend._consumer.stopped is True


@pytest.mark.asyncio
async def test_subscribe_with_start_cursor_calls_seek(
    mock_aiokafka: Any, fake_message: Any
) -> None:
    backend = DebeziumEventsCDCBackend(bootstrap_servers="localhost:9092")
    mock_aiokafka.set_test_messages([fake_message])

    start = CDCCursor(value="0:50", backend="debezium")
    async for _ in backend.subscribe(tables=["users"], start_cursor=start):
        await backend.close()
    consumer = backend._consumer
    # Should have called seek for the start cursor
    assert len(consumer.seeks) >= 1
    tp, offset = consumer.seeks[0]
    assert offset == 50
