# ruff: noqa: S101
"""Unit-тесты RagQueryProcessor strategy-расширения (S11 K3 W3 — Phase B.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from unittest.mock import AsyncMock

import pytest
import yaml

from src.backend.dsl.builder import RouteBuilder
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors import RagQueryProcessor
from src.backend.dsl.yaml_loader import load_pipeline_from_yaml


def _ex(body: Any = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers={}))


@dataclass(slots=True)
class _StubAugmentResult:
    """Минимальная реплика AugmentResult.to_dict()."""

    prompt: str = ""
    chunks: list[dict[str, Any]] = field(default_factory=list)
    worst_freshness: str = "fresh"

    def to_dict(self) -> dict[str, Any]:
        return {
            "prompt": self.prompt,
            "chunks": self.chunks,
            "worst_freshness": self.worst_freshness,
        }


class _StubRag:
    """Минимальный stub :class:`RAGService` для unit-тестов."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def augment(
        self,
        *,
        query: str,
        system_prompt: str = "",
        top_k: int = 5,
        namespace: str | None = None,
        max_staleness_hours: float | None = None,
    ) -> _StubAugmentResult:
        self.calls.append(
            {
                "query": query,
                "system_prompt": system_prompt,
                "top_k": top_k,
                "namespace": namespace,
                "max_staleness_hours": max_staleness_hours,
            }
        )
        return _StubAugmentResult(prompt=f"P({query})")


@pytest.fixture
def stub_rag(monkeypatch: pytest.MonkeyPatch) -> _StubRag:
    stub = _StubRag()
    monkeypatch.setattr(
        "src.backend.services.ai.rag_service.get_rag_service", lambda: stub
    )
    return stub


def test_strategy_enum_validation() -> None:
    """Невалидная стратегия → ValueError на конструировании."""
    with pytest.raises(ValueError):
        RagQueryProcessor(strategy="bogus")


@pytest.mark.parametrize("strategy", ["dense", "hybrid", "hyde", "multi_query"])
def test_strategy_enum_accepts_known(strategy: str) -> None:
    """Все 4 поддерживаемые стратегии валидны."""
    RagQueryProcessor(strategy=strategy)  # ничего не должно бросать


@pytest.mark.asyncio
async def test_max_staleness_propagated(stub_rag: _StubRag) -> None:
    """max_staleness_hours передаётся в RAGService.augment."""
    proc = RagQueryProcessor(strategy="dense", max_staleness_hours=24.0)
    exchange = _ex(body={"question": "Что нового?"})
    await proc.process(exchange, AsyncMock())
    assert stub_rag.calls[0]["max_staleness_hours"] == 24.0


@pytest.mark.asyncio
async def test_strategy_emits_into_property_and_payload(stub_rag: _StubRag) -> None:
    """strategy виден в exchange property и в augment_result payload."""
    proc = RagQueryProcessor(strategy="hybrid")
    exchange = _ex(body={"question": "Кто звонил?"})
    await proc.process(exchange, AsyncMock())
    assert exchange.get_property("rag_strategy") == "hybrid"
    payload = exchange.get_property("augment_result")
    assert payload["strategy"] == "hybrid"


def test_rag_query_to_spec_round_trip() -> None:
    """builder.rag_query(...) → YAML → builder идентичны."""
    builder = RouteBuilder.from_("rt.rag.query", source="test:rt.rag")
    builder.rag_query(strategy="multi_query", top_k=3, namespace="kb")
    pipeline = builder.build()
    dump = pipeline.to_dict()
    yaml_str = yaml.safe_dump(dump, sort_keys=False, allow_unicode=True)
    rebuilt = load_pipeline_from_yaml(yaml_str)
    assert dump == rebuilt.to_dict()


def test_default_strategy_dense_omitted_from_spec() -> None:
    """strategy="dense" (default) не пишется в spec — minimal payload."""
    proc = RagQueryProcessor()
    spec = proc.to_spec()
    assert spec == {"rag_query": {}}
