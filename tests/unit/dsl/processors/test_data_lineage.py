"""Unit tests for DataLineageProcessor + DataLineageMixin.

v21 §2.1: Data Lineage / Provenance. EU AI Act, RAG provenance, OpenLineage.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.data_lineage import (
    DataLineageProcessor,
    LineageEvent,
    LineageNode,
    LineageNodeType,
)


def _ex(body: Any = None, headers: dict[str, str] | None = None) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers=headers or {}),
        out_message=Message(body=body, headers=dict(headers or {})),
    )


# ── LineageNode / LineageEvent dataclasses ─────────────────────────────


def test_lineage_node_defaults() -> None:
    node = LineageNode(id="dataset:foo", type=LineageNodeType.DATASET, name="foo")
    assert node.id == "dataset:foo"
    assert node.type == LineageNodeType.DATASET
    assert node.name == "foo"
    assert node.attributes == {}


def test_lineage_node_with_attributes() -> None:
    node = LineageNode(
        id="dataset:foo",
        type=LineageNodeType.DATASET,
        name="foo",
        attributes={"source_uri": "s3://x", "version": "1.0"},
    )
    assert node.attributes["source_uri"] == "s3://x"
    assert node.attributes["version"] == "1.0"


def test_lineage_event_to_dict() -> None:
    node = LineageNode(
        id="dataset:foo",
        type=LineageNodeType.DATASET,
        name="foo",
        attributes={"source_uri": "s3://x"},
    )
    event = LineageEvent(
        event_id="ev-1",
        run_id="run-1",
        event_type="input",
        node=node,
        parent_ids=("dataset:bar",),
        payload={"tenant": "t1"},
    )
    d = event.to_dict()
    assert d["event_id"] == "ev-1"
    assert d["run_id"] == "run-1"
    assert d["event_type"] == "input"
    assert d["node"]["id"] == "dataset:foo"
    assert d["node"]["type"] == "dataset"
    assert d["node"]["attributes"]["source_uri"] == "s3://x"
    assert d["parent_ids"] == ["dataset:bar"]
    assert d["payload"] == {"tenant": "t1"}


# ── DataLineageProcessor: validation ────────────────────────────────────


def test_processor_validates_dataset() -> None:
    with pytest.raises(ValueError, match="dataset обязателен"):
        DataLineageProcessor(dataset="")  # type: ignore[arg-type]


def test_processor_validates_event_type() -> None:
    with pytest.raises(ValueError, match="event_type должен быть"):
        DataLineageProcessor(dataset="foo", event_type="invalid")


# ── DataLineageProcessor: process() ─────────────────────────────────────


@pytest.mark.asyncio
async def test_process_emits_event_to_emitter() -> None:
    """Capture: emitter receives 1 event, exchange.properties stores it."""
    received: list[LineageEvent] = []

    def emitter(event: LineageEvent) -> None:
        received.append(event)

    proc = DataLineageProcessor(
        dataset="customer_docs",
        source_uri="s3://docs/customer.json",
        capture_fields=["tenant", "doc_id"],
        lineage_emitter=emitter,
    )
    exchange = _ex(body={"tenant": "t1", "doc_id": "d1", "extra": "ignored"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    # Emitter received 1 event
    assert len(received) == 1
    event = received[0]
    assert event.node.type == LineageNodeType.DATASET
    assert event.node.name == "customer_docs"
    assert event.node.attributes["source_uri"] == "s3://docs/customer.json"
    # Captured fields
    assert event.payload["tenant"] == "t1"
    assert event.payload["doc_id"] == "d1"
    # Not captured (not in capture_fields)
    assert "extra" not in event.payload
    # Default event_type
    assert event.event_type == "transform"


@pytest.mark.asyncio
async def test_process_appends_to_exchange_properties() -> None:
    """exchange.properties['lineage_event'] stored для downstream."""
    proc = DataLineageProcessor(dataset="foo", lineage_emitter=lambda e: None)
    exchange = _ex(body={"x": 1})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert "lineage_event" in exchange.properties
    stored = exchange.properties["lineage_event"]
    assert stored["event_type"] == "transform"
    assert stored["node"]["name"] == "foo"


@pytest.mark.asyncio
async def test_process_captures_from_headers() -> None:
    """capture_fields lookup в headers если не в body."""
    proc = DataLineageProcessor(
        dataset="foo",
        capture_fields=["tenant_id"],
        lineage_emitter=lambda e: None,
    )
    exchange = _ex(body={"other": 1}, headers={"tenant_id": "tenant-42"})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    event = exchange.properties["lineage_event"]
    assert event["payload"]["tenant_id"] == "tenant-42"


@pytest.mark.asyncio
async def test_process_with_derive_from() -> None:
    """derive_from → parent_ids includes it."""
    proc = DataLineageProcessor(
        dataset="rag_chunks",
        derive_from="dataset:customer_docs",
        lineage_emitter=lambda e: None,
    )
    exchange = _ex(body={"chunks": ["c1", "c2"]})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    event = exchange.properties["lineage_event"]
    assert event["parent_ids"] == ["dataset:customer_docs"]


@pytest.mark.asyncio
async def test_process_input_event_type() -> None:
    proc = DataLineageProcessor(
        dataset="foo",
        event_type="input",
        lineage_emitter=lambda e: None,
    )
    exchange = _ex(body={})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.properties["lineage_event"]["event_type"] == "input"


@pytest.mark.asyncio
async def test_process_output_event_type() -> None:
    proc = DataLineageProcessor(
        dataset="foo",
        event_type="output",
        node_type=LineageNodeType.OUTPUT,
        lineage_emitter=lambda e: None,
    )
    exchange = _ex(body={})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    event = exchange.properties["lineage_event"]
    assert event["event_type"] == "output"
    assert event["node"]["type"] == "output"


@pytest.mark.asyncio
async def test_process_run_id_auto_generated() -> None:
    """run_id=None → auto-generated UUID (per-call)."""
    proc = DataLineageProcessor(dataset="foo", lineage_emitter=lambda e: None)
    exchange = _ex(body={})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    run_id = exchange.properties["lineage_event"]["run_id"]
    assert isinstance(run_id, str)
    assert len(run_id) > 0


@pytest.mark.asyncio
async def test_process_run_id_explicit() -> None:
    proc = DataLineageProcessor(
        dataset="foo", run_id="custom-run-123", lineage_emitter=lambda e: None
    )
    exchange = _ex(body={})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    assert exchange.properties["lineage_event"]["run_id"] == "custom-run-123"


@pytest.mark.asyncio
async def test_process_uses_default_emitter() -> None:
    """Default emitter — module-level in-memory store."""
    from src.backend.services.lineage import get_lineage_emitter

    emitter = get_lineage_emitter()
    emitter.clear()

    proc = DataLineageProcessor(dataset="foo")
    exchange = _ex(body={"x": 1})
    await proc.process(exchange, None)  # type: ignore[arg-type]

    events = emitter.list()
    assert len(events) == 1
    assert events[0]["node"]["name"] == "foo"


# ── Side effect classification ─────────────────────────────────────────


def test_processor_side_effects() -> None:
    from src.backend.core.types.side_effect import SideEffectKind

    proc = DataLineageProcessor(dataset="foo")
    assert proc.side_effect == SideEffectKind.PURE
    assert proc.compensatable is True
