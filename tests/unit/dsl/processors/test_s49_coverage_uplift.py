"""Additional coverage tests for S49 modules (push 92% → 98%+)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.data_lineage import DataLineageProcessor
from src.backend.dsl.processors.event_store import (
    EventStoreProcessor,
    InMemoryEventStore,
    get_event_store,
    reset_event_store,
    set_event_store,
)
from src.backend.services.ai.rag.lineage import RAGLineageTracker
from src.backend.services.lineage import (
    InMemoryLineageEmitter,
    get_lineage_emitter,
    reset_lineage_emitter,
)


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}),
        out_message=Message(body=body, headers={}),
    )


# ── data_lineage.py: async emitter, non-list existing, parent_ids from derive_from ──


@pytest.mark.asyncio
async def test_process_async_emitter() -> None:
    """Async emitter → await emit_result."""
    import asyncio

    received: list[Any] = []

    async def async_emitter(event: Any) -> None:
        await asyncio.sleep(0)
        received.append(event)

    proc = DataLineageProcessor(dataset="foo", lineage_emitter=async_emitter)
    ex = _ex(body={"x": 1})
    await proc.process(ex, None)  # type: ignore[arg-type]
    assert len(received) == 1


@pytest.mark.asyncio
async def test_process_appends_to_non_list_existing() -> None:
    """If existing lineage_events is non-list → reset to []."""
    proc = DataLineageProcessor(dataset="foo", lineage_emitter=lambda e: None)
    ex = _ex(body={"x": 1})
    ex.set_property("lineage_events", "corrupted_string")
    await proc.process(ex, None)  # type: ignore[arg-type]
    # New event should be in a list
    events = ex.properties["lineage_events"]
    assert isinstance(events, list)
    assert len(events) == 1


@pytest.mark.asyncio
async def test_process_capture_missing_field() -> None:
    """capture_field not in body/headers → not in payload."""
    proc = DataLineageProcessor(
        dataset="foo", capture_fields=["nonexistent"], lineage_emitter=lambda e: None
    )
    ex = _ex(body={"other": 1})
    await proc.process(ex, None)  # type: ignore[arg-type]
    event = ex.properties["lineage_event"]
    assert "nonexistent" not in event["payload"]


# ── event_store.py: get_event_store singleton race, set/reset ──


def test_set_event_store_replaces() -> None:
    """set_event_store replaces singleton."""
    custom = InMemoryEventStore()
    set_event_store(custom)
    assert get_event_store() is custom
    # Reset для clean state
    reset_event_store()


def test_event_store_processor_captures_from_body_dict_path() -> None:
    """Processor reads events from body when properties don't have them."""
    reset_event_store()
    proc = EventStoreProcessor()
    ex = _ex(body={"events": [{"aggregate_id": "o-1", "event_type": "x", "data": 1}]})
    # Manually call since this is sync test
    import asyncio

    asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
    events = get_event_store().load("o-1")
    assert len(events) == 1
    assert events[0].payload == {"data": 1}


def test_event_store_processor_no_body_no_properties() -> None:
    """Body is not dict → no events found."""
    reset_event_store()
    proc = EventStoreProcessor()
    ex = _ex(body="not a dict")
    import asyncio

    asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
    assert get_event_store().list_all() == []


def test_event_store_processor_body_with_none_events() -> None:
    """Body is dict but no 'events' key → no-op."""
    reset_event_store()
    proc = EventStoreProcessor()
    ex = _ex(body={"other": 1})
    import asyncio

    asyncio.run(proc.process(ex, None))  # type: ignore[arg-type]
    assert get_event_store().list_all() == []


# ── RAG lineage: emit creates event with response_id ──


def test_rag_lineage_tracker_default_response_id() -> None:
    """Response ID auto-generated."""
    reset_lineage_emitter()
    tracker = RAGLineageTracker(llm_model="gpt-4o")
    tracker.add_chunk_source(
        chunk_id="c-1",
        source_doc_id="d-1",
        source_doc_version="v1",
        embedding_model="emb",
        retrieval_score=0.9,
    )
    event = tracker.emit()
    assert event["node"]["name"].startswith("rag_response:")
    # response_id is in node attributes
    assert "response_id" in event["node"]["attributes"]


# ── lineage_emitter: to_openlineage with multiple attributes, custom emitter ──


def test_emitter_to_openlineage_with_attributes() -> None:
    """to_openlineage formats attributes in documentation facet."""
    em = InMemoryLineageEmitter()
    em(
        {
            "event_id": "e1",
            "run_id": "r1",
            "event_type": "output",
            "node": {
                "id": "d:foo",
                "type": "dataset",
                "name": "foo",
                "attributes": {"k1": "v1", "k2": 42},
            },
            "parent_ids": [],
            "timestamp": 1700000000.0,
            "payload": {},
        }
    )
    ol = em.to_openlineage()
    desc = ol[0]["outputs"][0]["facets"]["documentation"]["description"]
    assert "k1='v1'" in desc
    assert "k2=42" in desc


def test_emitter_to_openlineage_no_attributes() -> None:
    """to_openlineage handles missing attributes key."""
    em = InMemoryLineageEmitter()
    em(
        {
            "event_id": "e1",
            "run_id": "r1",
            "event_type": "output",
            "node": {"id": "d:foo", "type": "dataset", "name": "foo"},
            "parent_ids": [],
            "timestamp": 1700000000.0,
            "payload": {},
        }
    )
    ol = em.to_openlineage()
    # Should not crash
    assert len(ol) == 1


def test_emitter_to_openlineage_no_parent_ids() -> None:
    """to_openlineage handles missing parent_ids key."""
    em = InMemoryLineageEmitter()
    em(
        {
            "event_id": "e1",
            "run_id": "r1",
            "event_type": "output",
            "node": {"id": "d:foo", "type": "dataset", "name": "foo", "attributes": {}},
            "timestamp": 1700000000.0,
            "payload": {},
        }
    )
    ol = em.to_openlineage()
    assert ol[0]["inputs"] == []


def test_emitter_protocol_via_call() -> None:
    """InMemoryLineageEmitter matches LineageEmitterProtocol."""
    em = InMemoryLineageEmitter()
    # Protocol methods
    em({"event_id": "e1"})
    assert isinstance(em.list_events(), list)
    em.clear()
    assert em.list_events() == []
    assert isinstance(em.to_openlineage(), list)


def test_get_lineage_emitter_creates_singleton() -> None:
    """get_lineage_emitter creates new instance when None."""
    # This tests the singleton creation path
    from src.backend.services.lineage import lineage_emitter as le_module

    # Force re-creation
    le_module._emitter = None
    em = get_lineage_emitter()
    assert em is not None
    assert isinstance(em, InMemoryLineageEmitter)
