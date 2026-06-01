# ruff: noqa: S101
"""Unit-тесты RagIngestProcessor (S11 K3 W2 — Phase B.1)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors import RagIngestProcessor
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _ex(body: Any = None) -> Exchange[Any]:
    """Helper: создать Exchange с переданным body."""
    return Exchange(in_message=Message(body=body, headers={}))


class _StubRag:
    """Минимальный stub RAGService."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def ingest(
        self,
        *,
        content: str,
        metadata: dict[str, Any] | None = None,
        namespace: str = "default",
    ) -> str:
        self.calls.append(
            {"content": content, "metadata": metadata, "namespace": namespace}
        )
        return "doc-id-42"


@pytest.fixture
def stub_rag(monkeypatch: pytest.MonkeyPatch) -> _StubRag:
    """Подменяет get_rag_service в модуле processor'а."""
    stub = _StubRag()
    monkeypatch.setattr(
        "src.backend.services.ai.rag_service.get_rag_service", lambda: stub
    )
    return stub


@pytest.mark.asyncio
async def test_ingest_calls_rag_service_with_body(stub_rag: _StubRag) -> None:
    """Без source_property body уходит в RAGService.ingest как content."""
    proc = RagIngestProcessor(collection="docs")
    exchange = _ex(body="The quick brown fox")
    await proc.process(exchange, AsyncMock())

    assert stub_rag.calls == [
        {
            "content": "The quick brown fox",
            "metadata": {"modal": "text", "collection": "docs"},
            "namespace": "docs",
        }
    ]
    assert exchange.get_property("ingest_doc_id") == "doc-id-42"


@pytest.mark.asyncio
async def test_ingest_uses_source_property(stub_rag: _StubRag) -> None:
    """source_property переопределяет body — content берётся из property."""
    proc = RagIngestProcessor(source_property="document", collection="kb")
    exchange = _ex(body={"ignore": "me"})
    exchange.set_property("document", "Hello world")
    await proc.process(exchange, AsyncMock())

    assert stub_rag.calls[0]["content"] == "Hello world"
    assert stub_rag.calls[0]["namespace"] == "kb"


@pytest.mark.asyncio
async def test_ingest_modal_in_metadata(stub_rag: _StubRag) -> None:
    """modal сохраняется в metadata для downstream multimodal-консьюмеров."""
    proc = RagIngestProcessor(modal="image", collection="img")
    exchange = _ex(body="binary-as-string-stub")
    await proc.process(exchange, AsyncMock())

    assert stub_rag.calls[0]["metadata"]["modal"] == "image"


@pytest.mark.asyncio
async def test_ingest_empty_body_is_noop(stub_rag: _StubRag) -> None:
    """Пустое body не вызывает rag.ingest и не пишет doc_id."""
    proc = RagIngestProcessor(collection="docs")
    exchange = _ex(body="")
    await proc.process(exchange, AsyncMock())

    assert stub_rag.calls == []
    assert exchange.get_property("ingest_doc_id") is None


def test_rag_ingest_to_spec_round_trip() -> None:
    """builder.rag_ingest(...) → YAML → builder идентичны."""
    builder = RouteBuilder.from_("rt.rag.ingest", source="test:rt.rag")
    builder.rag_ingest(collection="kb", modal="image", source_property="doc")
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    assert dump == rebuilt.to_dict()


def test_rag_ingest_spec_minimal_default() -> None:
    """to_spec для минимальной конфигурации — только collection."""
    proc = RagIngestProcessor(collection="docs")
    spec = proc.to_spec()
    assert spec == {"rag_ingest": {"collection": "docs"}}
