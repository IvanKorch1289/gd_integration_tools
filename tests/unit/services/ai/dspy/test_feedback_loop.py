"""TDD: DSPy feedback loop integration (S171 M28-P1-3, D287).

Pattern (D287, Ponytail): thin wrapper над dspy.
Replace manual LLM optimization with DSPy signature/optimizer.
"""
# ruff: noqa: S101
from __future__ import annotations

import pytest


class TestDSPyFeedbackLoop:
    def test_instantiate_dspy_optimizer(self) -> None:
        """DSPyFeedbackTrainer — wrapper для dspy signature-based optimization."""
        from src.backend.services.ai.dspy.feedback_trainer import (
            DSPyFeedbackTrainer,
        )
        trainer = DSPyFeedbackTrainer()
        assert trainer is not None

    def test_collect_feedback(self) -> None:
        """collect_feedback() собирает feedback из dataset."""
        from src.backend.services.ai.dspy.feedback_trainer import (
            DSPyFeedbackTrainer,
        )
        trainer = DSPyFeedbackTrainer()
        feedback = trainer.collect_feedback(items=[
            {"input": "q1", "expected": "a1", "actual": "a1", "score": 1.0},
            {"input": "q2", "expected": "a2", "actual": "wrong", "score": 0.0},
        ])
        assert feedback["total"] == 2
        assert feedback["correct"] == 1
        assert feedback["accuracy"] == 0.5

    def test_optimize_stub(self) -> None:
        """optimize() — stub (D287, full DSPy в M28+)."""
        from src.backend.services.ai.dspy.feedback_trainer import (
            DSPyFeedbackTrainer,
        )
        trainer = DSPyFeedbackTrainer()
        result = trainer.optimize()
        # Stub returns current config
        assert result is not None
        assert "status" in result
