"""Unit tests for lineage emitter (in-memory + OpenLineage serialization)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.services.lineage import (
    InMemoryLineageEmitter,
    get_lineage_emitter,
    reset_lineage_emitter,
    set_lineage_emitter,
)
from src.backend.services.lineage.lineage_emitter import _iso_timestamp


def test_emitter_appends_event() -> None:
    em = InMemoryLineageEmitter()
    em({"event_id": "e1", "node": {"name": "foo"}})
    em({"event_id": "e2", "node": {"name": "bar"}})
    assert len(em.list_events()) == 2


def test_emitter_clear() -> None:
    em = InMemoryLineageEmitter()
    em({"event_id": "e1"})
    em.clear()
    assert em.list_events() == []


def test_emitter_rejects_invalid_event() -> None:
    em = InMemoryLineageEmitter()
    with pytest.raises(TypeError, match="должен быть LineageEvent или dict"):
        em("not an event")  # type: ignore[arg-type]


def test_emitter_accepts_lineage_event_with_to_dict() -> None:
    """Process LineageEvent objects via .to_dict() protocol."""
    from src.backend.dsl.processors.data_lineage import (
        LineageEvent,
        LineageNode,
        LineageNodeType,
    )

    em = InMemoryLineageEmitter()
    node = LineageNode(
        id="dataset:foo", type=LineageNodeType.DATASET, name="foo"
    )
    event = LineageEvent(
        event_id="e1", run_id="r1", event_type="input", node=node
    )
    em(event)
    stored = em.list_events()
    assert len(stored) == 1
    assert stored[0]["event_id"] == "e1"
    assert stored[0]["node"]["name"] == "foo"


def test_emitter_to_openlineage() -> None:
    em = InMemoryLineageEmitter()
    em(
        {
            "event_id": "e1",
            "run_id": "r1",
            "event_type": "output",
            "node": {
                "id": "dataset:foo",
                "type": "dataset",
                "name": "foo",
                "attributes": {"source_uri": "s3://x"},
            },
            "parent_ids": ["dataset:bar"],
            "timestamp": 1700000000.0,
            "payload": {"x": 1},
        }
    )
    ol_events = em.to_openlineage()
    assert len(ol_events) == 1
    ol = ol_events[0]
    assert ol["eventType"] == "COMPLETE"
    assert ol["run"]["runId"] == "r1"
    assert ol["job"]["name"] == "foo"
    assert ol["job"]["namespace"] == "dataset"
    assert ol["inputs"] == [{"namespace": "dataset", "name": "dataset:bar"}]
    assert len(ol["outputs"]) == 1
    assert ol["outputs"][0]["name"] == "dataset:foo"
    assert ol["outputs"][0]["facets"]["documentation"]["description"]


def test_emitter_thread_safe() -> None:
    """Append из multiple threads — lock должен защитить."""
    import threading

    em = InMemoryLineageEmitter()

    def append_many(start: int) -> None:
        for i in range(100):
            em({"event_id": f"e{start + i}"})

    threads = [
        threading.Thread(target=append_many, args=(i * 100,))
        for i in range(5)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(em.list_events()) == 500


# ── Module-level singleton ──────────────────────────────────────────────


def test_get_emitter_returns_singleton() -> None:
    e1 = get_lineage_emitter()
    e2 = get_lineage_emitter()
    assert e1 is e2


def test_set_emitter_replaces_singleton() -> None:
    custom = InMemoryLineageEmitter()
    set_lineage_emitter(custom)
    assert get_lineage_emitter() is custom


def test_reset_emitter_returns_fresh() -> None:
    em = get_lineage_emitter()
    em({"event_id": "e1"})
    fresh = reset_lineage_emitter()
    assert fresh is not em
    # New emitter is empty
    assert fresh.list_events() == []
    # Old emitter cleared (reset_lineage_emitter clears old instance first)
    assert em.list_events() == []


# ── ISO timestamp helper ────────────────────────────────────────────────


def test_iso_timestamp_format() -> None:
    iso = _iso_timestamp(1700000000.0)
    assert iso.endswith("Z")
    assert "T" in iso
    assert iso.startswith("2023-")


# ── RAG lineage tracker ────────────────────────────────────────────────


def test_rag_lineage_tracker_emits_event() -> None:
    from src.backend.services.ai.rag.lineage import RAGLineageTracker

    reset_lineage_emitter()
    tracker = RAGLineageTracker(
        run_id="run-rag-1",
        user_query="What is the capital of France?",
        llm_model="gpt-4o",
        prompt_template="qa_v3",
    )
    tracker.add_chunk_source(
        chunk_id="c-1",
        source_doc_id="doc-42",
        source_doc_version="2026-01-15",
        embedding_model="text-embedding-3-small",
        retrieval_score=0.92,
    )
    tracker.add_chunk_source(
        chunk_id="c-2",
        source_doc_id="doc-43",
        source_doc_version="2026-02-01",
        embedding_model="text-embedding-3-small",
        retrieval_score=0.85,
    )

    event = tracker.emit()
    assert event["event_type"] == "output"
    assert event["run_id"] == "run-rag-1"
    assert event["node"]["name"].startswith("rag_response:")
    assert event["payload"]["llm_model"] == "gpt-4o"
    assert event["payload"]["prompt_template"] == "qa_v3"
    assert len(event["payload"]["chunks"]) == 2
    assert event["payload"]["chunks"][0]["chunk_id"] == "c-1"
    assert event["payload"]["chunks"][0]["source_doc_id"] == "doc-42"


def test_rag_lineage_tracker_validates_score() -> None:
    from src.backend.services.ai.rag.lineage import RAGLineageTracker

    tracker = RAGLineageTracker(llm_model="gpt-4o")
    with pytest.raises(ValueError, match="retrieval_score должен быть"):
        tracker.add_chunk_source(
            chunk_id="c-1",
            source_doc_id="d-1",
            source_doc_version="v1",
            embedding_model="emb",
            retrieval_score=1.5,  # > 1.0
        )
