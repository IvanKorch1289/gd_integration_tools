"""Tests for langmem/rlm.py (cycle 70).

Stream E.7 Wave D.6 — Reinforcement Learning from Memory feedback.

RLMFeedbackProcessor.apply() applies feedback events ('good'/'bad'/'unclear')
to semantic-entry metadata. RLMConsolidator manages batch
consolidation with reindex hints when penalty threshold exceeded.

Cycle 70 invariant: tests catch regressions in feedback processing
that could corrupt semantic search ranking.
"""


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

pytestmark = pytest.mark.unit


class TestRLMSignalDataclass:
    """RLMSignal: data record для применённого feedback."""

    def test_to_dict_returns_all_fields(self) -> None:
        """to_dict() возвращает dict с всеми полями RLMSignal."""
        from src.backend.services.ai.memory.langmem.rlm import RLMSignal

        signal = RLMSignal(
            doc_id="doc-123",
            label="good",
            new_boost=5,
            new_penalty=0,
            reindex_hinted=False,
        )

        result = signal.to_dict()
        assert result == {
            "doc_id": "doc-123",
            "label": "good",
            "new_boost": 5,
            "new_penalty": 0,
            "reindex_hinted": False,
        }

    def test_to_dict_with_reindex_hint(self) -> None:
        """to_dict() preserves reindex_hinted=True."""
        from src.backend.services.ai.memory.langmem.rlm import RLMSignal

        signal = RLMSignal(
            doc_id="doc-bad",
            label="bad",
            new_boost=0,
            new_penalty=10,
            reindex_hinted=True,
        )
        result = signal.to_dict()
        assert result["reindex_hinted"] is True
        assert result["new_penalty"] == 10

    def test_slots_configured(self) -> None:
        """RLMSignal имеет __slots__ (memory-efficient)."""
        from src.backend.services.ai.memory.langmem.rlm import RLMSignal

        # slots-based classes не имеют __dict__.
        assert "__slots__" in RLMSignal.__dict__ or hasattr(
            RLMSignal, "__slots__"
        ), "RLMSignal should use __slots__ for memory efficiency"


class TestRLMFeedbackProcessorOnFeedback:
    """RLMFeedbackProcessor.on_feedback_received — applies feedback events."""

    @pytest.fixture
    def processor(self):
        """RLMFeedbackProcessor with reindex_threshold=10."""
        from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor

        return RLMFeedbackProcessor(reindex_threshold=10)

    @pytest.mark.asyncio
    async def test_on_feedback_received_good_no_qdrant(self, processor) -> None:
        """feedback 'good' when qdrant client unavailable → no-op return."""
        signal = await processor.on_feedback_received(
            doc_id="doc-1", label="good"
        )
        # No qdrant → returns zeroed signal.
        assert signal.doc_id == "doc-1"
        assert signal.label == "good"
        assert signal.new_boost == 0
        assert signal.new_penalty == 0
        assert signal.reindex_hinted is False

    @pytest.mark.asyncio
    async def test_on_feedback_received_bad_no_qdrant(self, processor) -> None:
        """feedback 'bad' when qdrant client unavailable → no-op return."""
        signal = await processor.on_feedback_received(
            doc_id="doc-2", label="bad"
        )
        # No qdrant → returns zeroed signal.
        assert signal.new_boost == 0
        assert signal.new_penalty == 0

    @pytest.mark.asyncio
    async def test_on_feedback_received_with_qdrant_good(self, processor) -> None:
        """feedback 'good' with qdrant → boost incremented in payload."""
        from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor

        # Mock langmem with qdrant client.
        mock_langmem = MagicMock()
        mock_langmem._client = MagicMock()
        mock_langmem._collection = "test"
        mock_langmem._client.retrieve = AsyncMock(
            return_value=[{"payload": {"rlm_boost": 5, "rlm_penalty": 0}}]
        )
        mock_langmem._client.upsert = AsyncMock()

        proc = RLMFeedbackProcessor(
            langmem_service=mock_langmem, reindex_threshold=10
        )

        signal = await proc.on_feedback_received(doc_id="doc-1", label="good")

        # boost incremented from 5 to 6.
        assert signal.new_boost == 6
        assert signal.new_penalty == 0
        # reindex_hinted not triggered (penalty < threshold).
        assert signal.reindex_hinted is False

    @pytest.mark.asyncio
    async def test_on_feedback_received_with_qdrant_bad_threshold(self, processor) -> None:
        """feedback 'bad' triggers reindex_hinted when penalty ≥ threshold."""
        from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor

        mock_langmem = MagicMock()
        mock_langmem._client = MagicMock()
        mock_langmem._collection = "test"
        # Start at penalty=9 (one short of threshold=10).
        mock_langmem._client.retrieve = AsyncMock(
            return_value=[{"payload": {"rlm_boost": 0, "rlm_penalty": 9}}]
        )
        mock_langmem._client.upsert = AsyncMock()

        proc = RLMFeedbackProcessor(
            langmem_service=mock_langmem, reindex_threshold=10
        )

        signal = await proc.on_feedback_received(doc_id="doc-1", label="bad")

        # penalty now 10, ≥ threshold → reindex_hinted=True.
        assert signal.new_penalty == 10
        assert signal.reindex_hinted is True


class TestRLMFeedbackProcessorAdjustScore:
    """RLMFeedbackProcessor.adjust_score — pure score recalculation (staticmethod)."""

    def test_adjust_score_with_rlm_disabled(self) -> None:
        """When langmem_settings.rlm_enabled=False → returns original score."""
        from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor

        # Mock langmem_settings with rlm_enabled=False.
        with patch(
            "src.backend.core.config.ai_stack.langmem_settings"
        ) as mock_settings:
            mock_settings.rlm_enabled = False
            mock_settings.rlm_boost_factor = 0.1

            result = RLMFeedbackProcessor.adjust_score(
                score=1.0, boost=10, penalty=5
            )
            # rlm disabled → returns original score.
            assert result == 1.0

    def test_adjust_score_with_rlm_enabled(self) -> None:
        """When rlm_enabled=True → score * (1 + (boost - penalty) * factor)."""
        from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor

        with patch(
            "src.backend.core.config.ai_stack.langmem_settings"
        ) as mock_settings:
            mock_settings.rlm_enabled = True
            mock_settings.rlm_boost_factor = 0.1

            # No boost/penalty change → no score change.
            result = RLMFeedbackProcessor.adjust_score(
                score=1.0, boost=5, penalty=5
            )
            # Formula: 1.0 * (1 + (5 - 5) * 0.1) = 1.0 * 1.0 = 1.0.
            assert result == pytest.approx(1.0)

            # Boost > 0 → score increases.
            result = RLMFeedbackProcessor.adjust_score(
                score=1.0, boost=10, penalty=0
            )
            # 1.0 * (1 + 10 * 0.1) = 1.0 * 2.0 = 2.0.
            assert result == pytest.approx(2.0)

            # Penalty > 0 → score decreases.
            result = RLMFeedbackProcessor.adjust_score(
                score=1.0, boost=0, penalty=10
            )
            # 1.0 * (1 + (0 - 10) * 0.1) = 1.0 * 0.0 = 0.0.
            assert result == pytest.approx(0.0)


class TestRLMConsolidator:
    """RLMConsolidator: batch consolidation manager."""

    def test_init_stores_qdrant_and_embedding(self) -> None:
        """__init__ stores qdrant and embedding_model attributes."""
        from src.backend.services.ai.memory.langmem.rlm import RLMConsolidator

        qdrant = MagicMock()
        proc = RLMConsolidator(
            qdrant_client=qdrant, embedding_model="custom-embed"
        )
        # Internal attributes (cycle 70 invariant: tests contract).
        assert proc.qdrant is qdrant
        assert proc.embedding_model == "custom-embed"
        # Threshold default is 0.3.
        assert proc.threshold == 0.3

    def test_init_default_embedding_model(self) -> None:
        """__init__ default embedding_model is MiniLM-L6-v2."""
        from src.backend.services.ai.memory.langmem.rlm import RLMConsolidator

        proc = RLMConsolidator(qdrant_client=MagicMock())
        assert "MiniLM" in proc.embedding_model or "all-" in proc.embedding_model
