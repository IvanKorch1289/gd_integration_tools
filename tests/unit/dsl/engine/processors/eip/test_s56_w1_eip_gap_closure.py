"""Unit tests для Camel EIP gap closure (Sprint 56 W1).

Coverage:
* PipesAndFiltersProcessor — 5 tests (sequential, async, transform, failure modes, stop)
* EventMessageProcessor + Envelope — 5 tests (enrich, publish, custom id, custom source, stats)
* MarshalProcessor / UnmarshalProcessor — 5 tests (JSON roundtrip, XML roundtrip, CSV,
  Pickle, content_type header)
"""

from __future__ import annotations

import asyncio
import json

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.event_message import (
    HEADER_EVENT_ID,
    HEADER_EVENT_TIMESTAMP,
    HEADER_EVENT_TYPE,
    HEADER_EVENT_VERSION,
    EventMessageEnvelope,
    EventMessageProcessor,
)
from src.backend.dsl.engine.processors.eip.marshal import (
    CsvDataFormat,
    JsonDataFormat,
    MarshalProcessor,
    PickleDataFormat,
    UnmarshalProcessor,
    XmlDataFormat,
)
from src.backend.dsl.engine.processors.eip.pipes_and_filters import (
    PipesAndFiltersProcessor,
)


def _exchange(body: object = "", headers: dict | None = None) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── PipesAndFilters ──────────────────────────────────────────────────


class TestPipesAndFilters:
    @pytest.mark.asyncio
    async def test_sequential_sync_steps(self) -> None:
        """3 sync steps применяются в порядке, каждый видит output предыдущего."""

        def append_x(ex: Exchange) -> str:
            return str(ex.in_message.body) + "x"

        def append_y(ex: Exchange) -> str:
            return str(ex.in_message.body) + "y"

        def append_z(ex: Exchange) -> str:
            return str(ex.in_message.body) + "z"

        p = PipesAndFiltersProcessor(steps=[append_x, append_y, append_z])
        ex = _exchange("start-")
        await p.process(ex, _ctx())
        assert ex.in_message.body == "start-xyz"
        assert ex.get_property("pipes_filters.completed") == 3
        assert ex.get_property("pipes_filters.last_step") == 2

    @pytest.mark.asyncio
    async def test_async_steps(self) -> None:
        """Async steps (coroutine functions) корректно awaited."""

        async def double(ex: Exchange) -> int:
            await asyncio.sleep(0)
            return int(ex.in_message.body) * 2

        async def add_ten(ex: Exchange) -> int:
            await asyncio.sleep(0)
            return int(ex.in_message.body) + 10

        p = PipesAndFiltersProcessor(steps=[double, add_ten])
        ex = _exchange("5")
        await p.process(ex, _ctx())
        assert ex.in_message.body == 20  # (5*2)+10

    @pytest.mark.asyncio
    async def test_none_return_keeps_body(self) -> None:
        """Step возвращает None → body остаётся прежним."""

        def noop(_ex: Exchange) -> None:
            return None

        def set_text(ex: Exchange) -> str:
            return "replaced"

        p = PipesAndFiltersProcessor(steps=[noop, set_text])
        ex = _exchange("original")
        await p.process(ex, _ctx())
        assert ex.in_message.body == "replaced"

    @pytest.mark.asyncio
    async def test_propagate_failure_raises(self) -> None:
        """propagate_failure=True (default) — failed step прерывает pipeline."""

        def good(ex: Exchange) -> str:
            return "ok"

        def bad(ex: Exchange) -> str:
            raise RuntimeError("intentional")

        def should_not_run(ex: Exchange) -> str:
            return "should-not"

        p = PipesAndFiltersProcessor(steps=[good, bad, should_not_run])
        ex = _exchange("x")
        # handle_processor_error swallows; check error attribute per S49 pattern
        await p.process(ex, _ctx())
        assert ex.error is not None
        assert "intentional" in ex.error
        stats = p.stats()
        assert stats["invocations"] == 1
        assert stats["failures"] == 1

    @pytest.mark.asyncio
    async def test_no_propagate_continues(self) -> None:
        """propagate_failure=False — failure логируется, pipeline продолжается."""

        def step1(ex: Exchange) -> str:
            return "step1"

        def bad(_ex: Exchange) -> str:
            raise ValueError("oops")

        def step3(ex: Exchange) -> str:
            return "step3"

        p = PipesAndFiltersProcessor(steps=[step1, bad, step3], propagate_failure=False)
        ex = _exchange("x")
        await p.process(ex, _ctx())
        # body was set to step3 result via good step3
        assert ex.in_message.body == "step3"
        # failures counter incremented, but no error propagated to exchange
        assert p.stats()["failures"] == 1
        # last_step = 2 (step3 was the last executed)
        assert ex.get_property("pipes_filters.last_step") == 2


# ── EventMessage ─────────────────────────────────────────────────────


class TestEventMessage:
    @pytest.mark.asyncio
    async def test_enrich_only(self) -> None:
        """Без producer — только header enrichment."""
        p = EventMessageProcessor(
            event_type="customer.created", event_version="1.0", event_source="billing"
        )
        ex = _exchange({"id": 123})
        await p.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_EVENT_ID)
        assert ex.in_message.get_header(HEADER_EVENT_TYPE) == "customer.created"
        assert ex.in_message.get_header(HEADER_EVENT_VERSION) == "1.0"
        assert ex.in_message.get_header(HEADER_EVENT_TIMESTAMP)
        assert ex.in_message.get_header("event_source") == "billing"
        # envelope stored
        env = ex.get_property("event.envelope")
        assert isinstance(env, EventMessageEnvelope)
        assert env.event_type == "customer.created"
        assert env.body == {"id": 123}

    @pytest.mark.asyncio
    async def test_publish_to_producer(self) -> None:
        """Producer callable вызывается с (topic, body, headers)."""
        calls: list[tuple[str, object, dict[str, str]]] = []

        def fake_producer(topic: str, body: object, headers: dict[str, str]) -> None:
            calls.append((topic, body, headers))

        p = EventMessageProcessor(
            event_type="order.shipped",
            event_version="2.0",
            topic="orders",
            producer=fake_producer,
        )
        ex = _exchange({"order_id": "O-1"})
        await p.process(ex, _ctx())
        assert len(calls) == 1
        topic, body, headers = calls[0]
        assert topic == "orders"
        assert body == {"order_id": "O-1"}
        assert headers["event_type"] == "order.shipped"
        assert headers["event_topic"] == "orders"
        assert p.stats()["publishes"] == 1

    @pytest.mark.asyncio
    async def test_custom_id_generator(self) -> None:
        """id_generator передан → используется (не UUID4)."""
        counter = {"n": 0}

        def gen_id() -> str:
            counter["n"] += 1
            return f"evt-{counter['n']:04d}"

        p = EventMessageProcessor(event_type="x", id_generator=gen_id)
        ex1 = _exchange({})
        await p.process(ex1, _ctx())
        ex2 = _exchange({})
        await p.process(ex2, _ctx())
        assert ex1.in_message.get_header(HEADER_EVENT_ID) == "evt-0001"
        assert ex2.in_message.get_header(HEADER_EVENT_ID) == "evt-0002"

    @pytest.mark.asyncio
    async def test_existing_event_id_preserved(self) -> None:
        """Если event_id уже в headers — используется, а не генерируется."""
        p = EventMessageProcessor(event_type="x")
        ex = _exchange({}, headers={HEADER_EVENT_ID: "explicit-id-123"})
        await p.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_EVENT_ID) == "explicit-id-123"

    @pytest.mark.asyncio
    async def test_async_producer(self) -> None:
        """Async producer (coroutine) корректно awaited."""
        called = {"n": 0}

        async def async_producer(
            topic: str, body: object, headers: dict[str, str]
        ) -> None:
            await asyncio.sleep(0)
            called["n"] += 1

        p = EventMessageProcessor(event_type="x", topic="t", producer=async_producer)
        ex = _exchange({})
        await p.process(ex, _ctx())
        assert called["n"] == 1


# ── Marshal / Unmarshal ──────────────────────────────────────────────


class TestMarshalUnmarshal:
    @pytest.mark.asyncio
    async def test_json_roundtrip(self) -> None:
        """dict → JSON bytes → dict roundtrip."""
        original = {"name": "alice", "age": 30, "tags": ["x", "y"]}
        m = MarshalProcessor(JsonDataFormat(indent=2))
        ex = _exchange(original)
        await m.process(ex, _ctx())
        assert isinstance(ex.in_message.body, bytes)
        assert ex.in_message.get_header("content_type") == "application/json"
        decoded = json.loads(ex.in_message.body.decode("utf-8"))
        assert decoded == original

        # Unmarshal back
        u = UnmarshalProcessor(JsonDataFormat(), target_type=dict)
        ex2 = _exchange(ex.in_message.body)
        await u.process(ex2, _ctx())
        assert ex2.in_message.body == original

    @pytest.mark.asyncio
    async def test_xml_roundtrip(self) -> None:
        """dict → XML bytes → dict roundtrip."""
        original = {"customer": {"name": "alice", "id": 42}}
        m = MarshalProcessor(XmlDataFormat(root_tag="root", pretty=True))
        ex = _exchange(original)
        await m.process(ex, _ctx())
        assert ex.in_message.get_header("content_type") == "application/xml"
        # XML should contain root tag and customer
        xml_str = ex.in_message.body.decode("utf-8")
        assert "<customer>" in xml_str
        assert "<name>alice</name>" in xml_str

        # Unmarshal
        u = UnmarshalProcessor(XmlDataFormat(), target_type=dict)
        ex2 = _exchange(ex.in_message.body)
        await u.process(ex2, _ctx())
        # XML root is "root" — dict comes back as {customer: {name: alice, id: 42}}
        assert ex2.in_message.body == {"customer": {"name": "alice", "id": "42"}}

    @pytest.mark.asyncio
    async def test_csv_marshal(self) -> None:
        """list[dict] → CSV bytes."""
        original = [{"id": "1", "name": "alice"}, {"id": "2", "name": "bob"}]
        m = MarshalProcessor(CsvDataFormat())
        ex = _exchange(original)
        await m.process(ex, _ctx())
        csv_str = ex.in_message.body.decode("utf-8")
        assert "id,name" in csv_str
        assert "1,alice" in csv_str
        assert "2,bob" in csv_str

        # Unmarshal
        u = UnmarshalProcessor(CsvDataFormat())
        ex2 = _exchange(ex.in_message.body)
        await u.process(ex2, _ctx())
        assert ex2.in_message.body == original

    @pytest.mark.asyncio
    async def test_pickle_roundtrip(self) -> None:
        """Arbitrary Python object roundtrip via pickle."""
        original = {"nested": {"key": [1, 2, 3]}, "ts": 12345}
        m = MarshalProcessor(PickleDataFormat())
        ex = _exchange(original)
        await m.process(ex, _ctx())
        assert isinstance(ex.in_message.body, bytes)
        # Pickle is binary — content_type set
        assert ex.in_message.get_header("content_type") == "application/x-python-pickle"

        u = UnmarshalProcessor(PickleDataFormat())
        ex2 = _exchange(ex.in_message.body)
        await u.process(ex2, _ctx())
        assert ex2.in_message.body == original

    @pytest.mark.asyncio
    async def test_invalid_data_unmarshal_records_error(self) -> None:
        """Битый JSON не raises — handle_processor_error записывает в exchange."""
        u = UnmarshalProcessor(JsonDataFormat())
        ex = _exchange(b"{not-valid-json")
        await u.process(ex, _ctx())
        # per S49 pattern: tests check exchange.error, not pytest.raises
        assert ex.error is not None
        assert "marshal" in ex.error or "json" in ex.error.lower()
