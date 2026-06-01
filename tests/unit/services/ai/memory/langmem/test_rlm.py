"""Тесты RLMFeedbackProcessor (Wave D.6)."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor


class _FakeQdrant:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.payload = initial or {}
        self.retrieve = AsyncMock(
            return_value=[{"id": "doc-1", "payload": self.payload}]
        )
        self.set_payload = AsyncMock()
        self.upsert = AsyncMock()


class _FakeLangmem:
    def __init__(self, client: _FakeQdrant) -> None:
        self._client = client
        self._collection = "langmem_semantic"


@pytest.mark.asyncio
async def test_good_feedback_increments_boost() -> None:
    client = _FakeQdrant({"rlm_boost": 1, "rlm_penalty": 0})
    langmem = _FakeLangmem(client)
    rlm = RLMFeedbackProcessor(langmem_service=langmem, reindex_threshold=5)
    signal = await rlm.on_feedback_received(doc_id="doc-1", label="good")
    assert signal.new_boost == 2
    assert signal.new_penalty == 0
    assert signal.reindex_hinted is False


@pytest.mark.asyncio
async def test_bad_feedback_increments_penalty_and_hints_reindex() -> None:
    client = _FakeQdrant({"rlm_boost": 0, "rlm_penalty": 2})
    langmem = _FakeLangmem(client)
    rlm = RLMFeedbackProcessor(langmem_service=langmem, reindex_threshold=3)
    signal = await rlm.on_feedback_received(doc_id="doc-1", label="bad")
    assert signal.new_penalty == 3
    assert signal.reindex_hinted is True


@pytest.mark.asyncio
async def test_unclear_label_leaves_counters_unchanged() -> None:
    client = _FakeQdrant({"rlm_boost": 2, "rlm_penalty": 1})
    langmem = _FakeLangmem(client)
    rlm = RLMFeedbackProcessor(langmem_service=langmem, reindex_threshold=5)
    signal = await rlm.on_feedback_received(doc_id="doc-1", label="unclear")
    assert signal.new_boost == 2
    assert signal.new_penalty == 1


def test_adjust_score_disabled_when_flag_off(monkeypatch) -> None:  # noqa: ANN001
    from src.backend.core.config import ai_2026 as cfg

    monkeypatch.setattr(cfg.langmem_settings, "rlm_enabled", False)
    assert RLMFeedbackProcessor.adjust_score(score=0.8, boost=5, penalty=0) == 0.8


def test_adjust_score_applies_factor_when_enabled(monkeypatch) -> None:  # noqa: ANN001
    from src.backend.core.config import ai_2026 as cfg

    monkeypatch.setattr(cfg.langmem_settings, "rlm_enabled", True)
    monkeypatch.setattr(cfg.langmem_settings, "rlm_boost_factor", 0.1)
    score = RLMFeedbackProcessor.adjust_score(score=0.5, boost=2, penalty=0)
    assert pytest.approx(score, rel=1e-6) == 0.5 * (1 + 2 * 0.1)
    score_neg = RLMFeedbackProcessor.adjust_score(score=0.5, boost=0, penalty=3)
    assert pytest.approx(score_neg, rel=1e-6) == 0.5 * (1 - 3 * 0.1)
