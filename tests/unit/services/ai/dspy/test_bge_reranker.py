"""Unit test для Block 3.1 (gap-ai-3.1, ADR-0074).

Проверяет :class:`_RagRerankerPipeline` с BGE cross-encoder:

1. ``BGESettings.reranker_enabled=False`` → fallback на token-overlap heuristic.
2. ``reranker_enabled=True`` + mock FlagReranker → используется
   cross-encoder, документы упорядочены по ``compute_score``.
3. ImportError ``FlagEmbedding`` → graceful fallback + counter inc.
4. ``compute_score`` raises (CUDA OOM) → graceful fallback на runtime.
"""

from __future__ import annotations

import json
import sys
from types import ModuleType
from typing import Any
from unittest.mock import MagicMock

import pytest


def _reset_reranker_cache() -> None:
    """Сбрасывает module-level кэш reranker — нужно между тестами."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod

    mod._reranker_cache = None
    mod._reranker_unavailable = False


@pytest.mark.unit
def test_fallback_to_token_overlap_when_reranker_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При reranker_enabled=False используется token-overlap heuristic."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", False, raising=True)
    _reset_reranker_cache()

    example = {
        "query": "credit risk assessment",
        "candidates": [
            {"id": "doc1", "text": "Credit risk model uses logistic regression"},
            {"id": "doc2", "text": "Weather forecast for tomorrow"},
            {"id": "doc3", "text": "Risk assessment in credit scoring is important"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    # token-overlap должен поставить doc3 (3 совпадения) и doc1 (2) выше doc2 (0).
    assert ranked[-1] == "doc2"


@pytest.mark.unit
def test_bge_reranker_used_when_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """При reranker_enabled=True + FlagEmbedding доступен → используется BGE."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    captured: dict[str, Any] = {}

    class _FakeFlagReranker:
        def __init__(self, model: str, **kwargs: Any) -> None:
            captured["model"] = model
            captured["kwargs"] = kwargs

        def compute_score(self, pairs: list[tuple[str, str]]) -> list[float]:
            # Преднамеренно возвращаем монотонно убывающий список —
            # первый кандидат выиграет независимо от текста.
            return [10.0, 5.0, 1.0]

    fake_mod = ModuleType("FlagEmbedding")
    fake_mod.FlagReranker = _FakeFlagReranker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_mod)

    example = {
        "query": "test",
        "candidates": [
            {"id": "a", "text": "x"},
            {"id": "b", "text": "y"},
            {"id": "c", "text": "z"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    # BGE поставил a→10, b→5, c→1 → ranked = [a, b, c].
    assert ranked == ["a", "b", "c"]
    assert captured["model"] == "BAAI/bge-reranker-v2-m3"


@pytest.mark.unit
def test_graceful_fallback_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ImportError FlagEmbedding → token-overlap + counter inc."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    captured: list[str] = []
    monkeypatch.setattr(
        mod, "_record_reranker_fallback", lambda *, reason: captured.append(reason)
    )

    # Эмулируем отсутствие FlagEmbedding через builtins.__import__.
    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def _fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
        if name.startswith("FlagEmbedding"):
            raise ImportError(f"эмуляция: {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", _fake_import)

    example = {
        "query": "credit",
        "candidates": [
            {"id": "doc1", "text": "credit model"},
            {"id": "doc2", "text": "weather"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    # Fallback на token-overlap: doc1 имеет "credit" → выигрывает.
    assert ranked[0] == "doc1"
    assert captured == ["import_error"]


@pytest.mark.unit
def test_graceful_fallback_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """FlagReranker.compute_score raises (CUDA OOM) → fallback + counter inc."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    captured: list[str] = []
    monkeypatch.setattr(
        mod, "_record_reranker_fallback", lambda *, reason: captured.append(reason)
    )

    class _FailingReranker:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def compute_score(self, pairs: list[tuple[str, str]]) -> list[float]:
            raise RuntimeError("CUDA out of memory")

    fake_mod = ModuleType("FlagEmbedding")
    fake_mod.FlagReranker = _FailingReranker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_mod)

    example = {
        "query": "credit",
        "candidates": [
            {"id": "doc1", "text": "credit"},
            {"id": "doc2", "text": "weather"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    # Fallback → token-overlap → doc1 первый.
    assert ranked[0] == "doc1"
    assert captured == ["runtime_error"]



@pytest.mark.unit
def test_reranker_unavailable_early_return(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покрывает early return при _reranker_unavailable=True (line 44)."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()
    mod._reranker_unavailable = True

    example = {
        "query": "credit",
        "candidates": [
            {"id": "doc1", "text": "credit model"},
            {"id": "doc2", "text": "weather"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    assert ranked[0] == "doc1"


@pytest.mark.unit
def test_reranker_cache_reuse(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покрывает reuse _reranker_cache (line 46)."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    init_calls = 0

    class _CountedReranker:
        def __init__(self, *_: Any, **__: Any) -> None:
            nonlocal init_calls
            init_calls += 1

        def compute_score(self, pairs: list[tuple[str, str]]) -> list[float]:
            return [1.0] * len(pairs)

    fake_mod = ModuleType("FlagEmbedding")
    fake_mod.FlagReranker = _CountedReranker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_mod)

    example = {
        "query": "q",
        "candidates": [{"id": "a", "text": "x"}],
    }
    rag_reranker_pipeline.forward(example)
    rag_reranker_pipeline.forward(example)
    assert init_calls == 1
    assert mod._reranker_cache is not None


@pytest.mark.unit
def test_fallback_on_bge_settings_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покрывает except при импорте bge_settings (lines 50-52)."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    _reset_reranker_cache()
    monkeypatch.delitem(sys.modules, "src.backend.core.config.ai_2026", raising=False)

    fake_mod = ModuleType("src.backend.core.config.ai_2026")
    monkeypatch.setitem(sys.modules, "src.backend.core.config.ai_2026", fake_mod)

    example = {
        "query": "credit",
        "candidates": [
            {"id": "doc1", "text": "credit model"},
            {"id": "doc2", "text": "weather"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    assert ranked[0] == "doc1"
    assert mod._reranker_unavailable is True


@pytest.mark.unit
def test_fallback_on_flag_reranker_init_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покрывает except при инициализации FlagReranker (lines 80-84)."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    class _BrokenInitReranker:
        def __init__(self, *_: Any, **__: Any) -> None:
            raise RuntimeError("init failed")

    fake_mod = ModuleType("FlagEmbedding")
    fake_mod.FlagReranker = _BrokenInitReranker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_mod)

    captured: list[str] = []
    monkeypatch.setattr(
        mod, "_record_reranker_fallback", lambda *, reason: captured.append(reason)
    )

    example = {
        "query": "credit",
        "candidates": [
            {"id": "doc1", "text": "credit"},
            {"id": "doc2", "text": "weather"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    assert ranked[0] == "doc1"
    assert captured == ["init_error"]
    assert mod._reranker_unavailable is True


@pytest.mark.unit
def test_forward_empty_query_or_candidates() -> None:
    """Покрывает early return при пустом query или candidates (line 124)."""
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    _reset_reranker_cache()

    example = {"query": "", "candidates": [{"id": "a", "text": "x"}]}
    output = rag_reranker_pipeline.forward(example)
    assert json.loads(output) == ["a"]

    example = {"query": "q", "candidates": []}
    output = rag_reranker_pipeline.forward(example)
    assert json.loads(output) == []


@pytest.mark.unit
def test_forward_compute_score_returns_scalar(monkeypatch: pytest.MonkeyPatch) -> None:
    """Покрывает scores = [scores] когда compute_score возвращает scalar (line 132)."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    monkeypatch.setattr(ai_2026.bge_settings, "reranker_enabled", True, raising=True)
    _reset_reranker_cache()

    class _ScalarReranker:
        def __init__(self, *_: Any, **__: Any) -> None:
            pass

        def compute_score(self, pairs: list[tuple[str, str]]) -> float:
            return 42.0

    fake_mod = ModuleType("FlagEmbedding")
    fake_mod.FlagReranker = _ScalarReranker  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "FlagEmbedding", fake_mod)

    example = {
        "query": "q",
        "candidates": [{"id": "a", "text": "x"}],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    assert ranked == ["a"]


@pytest.mark.unit
def test_forward_fallback_empty_doc_text() -> None:
    """Покрывает return 0.0 в _score при пустых doc_tokens (line 156)."""
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    _reset_reranker_cache()

    example = {
        "query": "credit risk",
        "candidates": [
            {"id": "doc1", "text": ""},
            {"id": "doc2", "text": "credit risk model"},
        ],
    }
    output = rag_reranker_pipeline.forward(example)
    ranked = json.loads(output)
    assert ranked[0] == "doc2"
    assert ranked[1] == "doc1"


@pytest.mark.unit
def test_record_reranker_fallback_success_and_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Покрывает _record_reranker_fallback: успешный inc и except-path (lines 89-99)."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod

    fake_counter = MagicMock()
    fake_registry = MagicMock()
    fake_registry.counter.return_value = fake_counter

    fake_metrics_mod = MagicMock()
    fake_metrics_mod.metrics_registry = fake_registry
    monkeypatch.setitem(
        sys.modules, "src.backend.core.utils.metrics_registry", fake_metrics_mod
    )

    mod._record_reranker_fallback(reason="test_reason")
    fake_registry.counter.assert_called_once_with(
        "rag_reranker_fallback_total",
        "Fallback на token-overlap reranker при недоступности BGE",
        labels=("reason",),
    )
    fake_counter.labels.assert_called_once_with(reason="test_reason")
    fake_counter.labels.return_value.inc.assert_called_once()

    # failure path — metrics_registry raises
    broken_registry = MagicMock()
    broken_registry.counter.side_effect = RuntimeError("metrics down")
    fake_metrics_mod.metrics_registry = broken_registry
    monkeypatch.setitem(
        sys.modules, "src.backend.core.utils.metrics_registry", fake_metrics_mod
    )
    mod._record_reranker_fallback(reason="fail")  # не падает


@pytest.mark.unit
def test_metric_ndcg() -> None:
    """Покрывает метод metric (lines 164-184)."""
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )

    # perfect ranking
    example = {
        "query": "q",
        "candidates": [{"id": "a"}, {"id": "b"}, {"id": "c"}],
        "expected_ranking": ["b", "a", "c"],
    }
    score = rag_reranker_pipeline.metric(example, json.dumps(["b", "a", "c"]))
    assert score == 1.0

    # imperfect ranking
    score = rag_reranker_pipeline.metric(example, json.dumps(["a", "b", "c"]))
    assert 0.0 < score < 1.0

    # empty predicted
    score = rag_reranker_pipeline.metric(example, json.dumps([]))
    assert score == 0.0

    # empty expected_ranking
    score = rag_reranker_pipeline.metric(
        {"query": "q", "candidates": [], "expected_ranking": []},
        json.dumps(["a"]),
    )
    assert score == 0.0

    # invalid json output
    score = rag_reranker_pipeline.metric(example, "not-json")
    assert score == 0.0
