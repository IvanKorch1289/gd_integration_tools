"""Unit-тесты для DSL processor search (S10 K3 W5)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.dsl.search.processor_search import (
    ProcessorSearch,
    SearchResult,
    tokenize,
)


@dataclass
class _FakeSpec:
    name: str
    namespace: str = "core"
    cls: type | None = None
    meta: dict[str, Any] = field(default_factory=dict)


class _HttpCallProc:
    """Отправляет HTTP-запрос с retry-policy и timeout."""


class _AuditProc:
    """Сохраняет audit event в immutable log."""


class _RagQueryProc:
    """Делает retrieval с hybrid search (BM25 + dense embeddings)."""


def test_tokenize_basic() -> None:
    assert tokenize("hello WORLD x") == {"hello", "world"}
    # длина < 2 фильтруется
    assert "x" not in tokenize("a x x")


def test_tokenize_russian() -> None:
    assert "запрос" in tokenize("отправить запрос на сервер")


def test_search_empty_query_returns_empty() -> None:
    s = ProcessorSearch.from_specs([_FakeSpec(name="x", cls=_HttpCallProc)])
    assert s.search("") == []


def test_search_returns_relevant_processor() -> None:
    specs = [
        _FakeSpec(name="http_call", cls=_HttpCallProc),
        _FakeSpec(name="audit", cls=_AuditProc),
        _FakeSpec(name="rag_query", cls=_RagQueryProc),
    ]
    s = ProcessorSearch.from_specs(specs)
    results = s.search("send http request with retry", top_k=3)
    assert results
    assert results[0].processor_name == "http_call"


def test_search_top_k_limits_results() -> None:
    specs = [_FakeSpec(name=f"p_{i}", cls=_HttpCallProc) for i in range(10)]
    s = ProcessorSearch.from_specs(specs)
    results = s.search("http", top_k=3)
    assert len(results) <= 3


def test_search_result_dataclass_immutable() -> None:
    r = SearchResult(
        processor_name="x", namespace="core", score=0.5, description="d"
    )
    with pytest.raises(AttributeError):
        r.score = 0.9  # type: ignore[misc]


def test_search_score_in_0_1_range() -> None:
    s = ProcessorSearch.from_specs(
        [_FakeSpec(name="http_call", cls=_HttpCallProc)]
    )
    r = s.search("http")
    assert r
    assert 0.0 <= r[0].score <= 1.0


def test_search_ignores_empty_tokens() -> None:
    s = ProcessorSearch.from_specs([_FakeSpec(name="empty_proc")])
    # пустой processor без docstring/meta — score ≤ 0 в любом случае.
    assert s.search("anything") == []
