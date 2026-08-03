"""Tests for hallucination_check eval suite (cycle 62).

S173 K4 W1 — Fabrication detection в RAG-ответах через
context overlap (faithfulness + fabrication_rate metrics).

This suite is critical for banking-grade AI quality:
- faithfulness = fraction of output tokens present in context
- fabrication_rate = fraction of output tokens NOT in context
- Lower fabrication_rate = better answer (grounded in context)

Cycle 62 invariant: these tests catch regressions in the
fabrication detection metric that could lead to silent hallucinations
in production.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


class TestHallucinationCheckSuite:
    """S173 K4 W1 — hallucination_check eval suite."""

    def test_suite_name(self) -> None:
        """Suite metadata: name and description are set."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        assert hallucination_check_suite.name == "hallucination_check"
        assert "fabrication" in hallucination_check_suite.description.lower()

    def test_suite_has_5_samples(self) -> None:
        """Suite имеет 5 образцов (RAG-context overlap scenarios)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        assert len(dataset) == 5, f"Expected 5 samples, got {len(dataset)}"
        # Each sample has expected keys.
        for sample in dataset:
            assert "id" in sample
            assert "context" in sample
            assert "question" in sample
            assert "expected" in sample

    def test_faithfulness_high_for_grounded_answer(self) -> None:
        """Answer directly from context → faithfulness ~ 1.0 (all tokens grounded)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        # Use sample 1 — context talks about Bank X, founded 1995, Moscow.
        sample = dataset[0]
        output = "Банк X основан в 1995 году"  # directly from context

        scores = hallucination_check_suite.score(sample, output)
        assert scores["faithfulness"] >= 0.99, (
            f"Direct context answer should have near-perfect faithfulness, "
            f"got {scores['faithfulness']}"
        )
        assert scores["fabrication_rate"] <= 0.01

    def test_fabrication_rate_high_for_invented_answer(self) -> None:
        """Answer NOT in context → high fabrication_rate."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        sample = dataset[0]  # context: Банк X 1995, Москва, лицензия 1234
        # Hallucinated answer — all words not in context.
        output = "Апельсины растут на марсианских плантациях с 1842 года"

        scores = hallucination_check_suite.score(sample, output)
        # Most tokens are not in context.
        assert scores["fabrication_rate"] > 0.5, (
            f"Hallucinated answer should have > 50% fabrication, "
            f"got {scores['fabrication_rate']}"
        )
        assert scores["faithfulness"] < 0.5

    def test_faithfulness_partial_for_mixed_answer(self) -> None:
        """Answer partially from context → partial faithfulness."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        sample = dataset[0]
        # Half from context, half hallucinated.
        output = "Банк X основан в 1995 году. Луна сделана из сыра."

        scores = hallucination_check_suite.score(sample, output)
        # Should be between 0 and 1 (mixed).
        assert 0.0 < scores["faithfulness"] < 1.0, (
            f"Mixed answer should have partial faithfulness, "
            f"got {scores['faithfulness']}"
        )
        assert 0.0 < scores["fabrication_rate"] < 1.0

    def test_score_handles_empty_output(self) -> None:
        """Empty output → zero scores (no fabrication possible)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        sample = dataset[0]

        scores = hallucination_check_suite.score(sample, "")
        assert scores["faithfulness"] == 0.0
        assert scores["fabrication_rate"] == 0.0

    def test_score_handles_empty_context(self) -> None:
        """Empty context → all output tokens are 'fabricated'."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        sample = {
            "id": "test",
            "context": "",
            "question": "?",
            "expected": "",
        }
        output = "любой текст с токенами"

        scores = hallucination_check_suite.score(sample, output)
        # All tokens in output are not in (empty) context → 100% fabrication.
        assert scores["faithfulness"] == 0.0
        assert scores["fabrication_rate"] == 1.0

    def test_score_handles_missing_context_key(self) -> None:
        """Sample без 'context' key → treated as empty context."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        sample = {"id": "test", "question": "?"}  # no context, no expected
        output = "какой-то текст"

        scores = hallucination_check_suite.score(sample, output)
        # All output tokens fabricated (no context).
        assert scores["faithfulness"] == 0.0
        assert scores["fabrication_rate"] == 1.0

    def test_score_is_case_insensitive(self) -> None:
        """Score treats context/output tokens case-insensitively (lowercase)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        sample = dataset[0]
        # Mixed case should be normalized for comparison.
        output = "БАНК X ОСНОВАН В 1995 ГОДУ"

        scores = hallucination_check_suite.score(sample, output)
        # After lowercasing, all tokens match the context.
        assert scores["faithfulness"] >= 0.99

    def test_score_unicode_tokens(self) -> None:
        """Tokenization handles Unicode (Russian bank content)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        # Sample 2: "Депозит «Доходный» имеет ставку 12% годовых"
        sample = dataset[1]
        output = "12% годовых по депозиту Доходный"

        scores = hallucination_check_suite.score(sample, output)
        # Russian tokenization works; faithfulness should be > 0.5
        # (some "по" / "депозиту" tokens are common forms and may not
        # exactly match — but core content "12%", "годовых", "Депозит",
        # "Доходный" must match).
        assert scores["faithfulness"] > 0.5, (
            f"Russian token match should be > 0.5, got {scores['faithfulness']}"
        )

    def test_score_metrics_sum_to_one(self) -> None:
        """faithfulness + fabrication_rate == 1.0 (complementary metrics)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        for sample in dataset:
            output = "Test output with some random text"
            scores = hallucination_check_suite.score(sample, output)
            # Should sum to 1.0 (faithfulness = grounded/total, fabrication = (total-grounded)/total).
            total = scores["faithfulness"] + scores["fabrication_rate"]
            assert abs(total - 1.0) < 1e-6, (
                f"faithfulness + fabrication_rate should sum to 1.0, "
                f"got {total} for sample {sample['id']}"
            )

    def test_samples_have_unique_ids(self) -> None:
        """Каждый sample имеет unique id (для eval reporting)."""
        from src.backend.services.ai.eval.suites.hallucination_check import (
            hallucination_check_suite,
        )

        dataset = hallucination_check_suite.build_dataset()
        ids = [s["id"] for s in dataset]
        assert len(ids) == len(set(ids)), (
            f"Sample ids should be unique, got duplicates: {ids}"
        )

    def test_suite_is_singleton(self) -> None:
        """Suite is exported as singleton (`hallucination_check_suite`)."""
        from src.backend.services.ai.eval.suites import hallucination_check

        # Module exports single instance via __all__.
        assert "hallucination_check_suite" in hallucination_check.__all__
        assert hallucination_check.hallucination_check_suite is not None
        # Accessing the singleton returns same object.
        same = hallucination_check.hallucination_check_suite
        assert same is hallucination_check.hallucination_check_suite
