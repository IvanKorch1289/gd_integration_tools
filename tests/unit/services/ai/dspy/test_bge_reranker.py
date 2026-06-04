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

import pytest


def _reset_reranker_cache() -> None:
    """Сбрасывает module-level кэш reranker — нужно между тестами."""
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod

    mod._reranker_cache = None
    mod._reranker_unavailable = False


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


def test_graceful_fallback_on_import_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """ImportError FlagEmbedding → token-overlap + counter inc."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod

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


def test_graceful_fallback_on_runtime_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """FlagReranker.compute_score raises (CUDA OOM) → fallback + counter inc."""
    from src.backend.core.config import ai_2026
    from src.backend.services.ai.dspy.pipelines.rag_reranker import (
        rag_reranker_pipeline,
    )
    import src.backend.services.ai.dspy.pipelines.rag_reranker as mod

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
