"""credit_scoring DSPy-pipeline (K4 S6 W2).

Принимает структурированный профиль клиента, возвращает decision/score.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _CreditScoringPipeline:
    name: str = "credit_scoring"
    description: str = "Credit decision (approve/reject) + score 0..1000"

    def forward(self, example: dict[str, Any]) -> str:
        """Базовая эвристика без оптимизации (используется как baseline)."""
        income = float(example.get("income_rub") or 0)
        score_input = int(example.get("credit_score") or 0)
        if score_input >= 700 and income >= 60000:
            decision = "approve"
        elif score_input >= 600:
            decision = "approve"
        elif score_input >= 500:
            decision = "review"
        else:
            decision = "reject"
        return json.dumps(
            {"decision": decision, "score": score_input}, ensure_ascii=False
        )

    def metric(self, example: dict[str, Any], output: str) -> float:
        """Возвращает 1.0 если decision совпадает, partial для score-mismatch."""
        try:
            parsed = json.loads(output)
        except Exception as _:  # noqa: BLE001
            return 0.0
        expected = example.get("expected")
        if isinstance(expected, str):
            try:
                expected_dict = json.loads(expected)
            except Exception as _:  # noqa: BLE001
                expected_dict = {}
        elif isinstance(expected, dict):
            expected_dict = expected
        else:
            return 0.0

        decision_match = (
            1.0 if parsed.get("decision") == expected_dict.get("decision") else 0.0
        )
        score_match = 0.0
        if (
            "score" in parsed
            and "score" in expected_dict
            and isinstance(parsed["score"], (int, float))
            and isinstance(expected_dict["score"], (int, float))
        ):
            diff = abs(parsed["score"] - expected_dict["score"])
            score_match = max(0.0, 1.0 - diff / 1000.0)

        return 0.7 * decision_match + 0.3 * score_match


credit_scoring_pipeline = _CreditScoringPipeline()
__all__ = ("credit_scoring_pipeline",)
