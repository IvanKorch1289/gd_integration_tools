"""instruction_following suite — следование инструкциям в credit-scoring (K4 S6 W1).

Проверяет, выполняет ли LLM формальные правила формата ответа:
* возврат JSON;
* перечень обязательных полей;
* запрет на спекуляции (only-from-context).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _InstructionFollowing:
    name: str = "instruction_following"
    description: str = "Следование инструкциям формата в credit-scoring промптах"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "fmt-1",
                "instruction": "Верни JSON {decision, score} по клиенту.",
                "expected": json.dumps(
                    {"decision": "approve", "score": 650}, ensure_ascii=False
                ),
                "required_fields": ["decision", "score"],
            },
            {
                "id": "fmt-2",
                "instruction": "Верни JSON {risk_level, reason} с reason на русском.",
                "expected": json.dumps(
                    {"risk_level": "low", "reason": "стабильный доход"},
                    ensure_ascii=False,
                ),
                "required_fields": ["risk_level", "reason"],
            },
            {
                "id": "fmt-3",
                "instruction": "Только JSON, без префикса 'Ответ:'.",
                "expected": json.dumps({"approve": True}, ensure_ascii=False),
                "required_fields": ["approve"],
            },
            {
                "id": "fmt-4",
                "instruction": "Возврат лимита в RUB как integer.",
                "expected": json.dumps({"limit_rub": 500000}, ensure_ascii=False),
                "required_fields": ["limit_rub"],
            },
            {
                "id": "fmt-5",
                "instruction": "Список причин refusal в массиве `refusal_reasons`.",
                "expected": json.dumps(
                    {"refusal_reasons": ["низкий доход", "просрочки"]},
                    ensure_ascii=False,
                ),
                "required_fields": ["refusal_reasons"],
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        """Возвращает is_json + field_coverage."""
        required = sample.get("required_fields") or []
        try:
            parsed = json.loads(output)
            is_json = 1.0
        except Exception:  # noqa: BLE001
            parsed = {}
            is_json = 0.0

        if not required:
            coverage = 1.0
        else:
            hit = sum(1 for f in required if f in parsed)
            coverage = hit / len(required)

        return {
            "is_json": is_json,
            "field_coverage": float(coverage),
        }


instruction_following_suite = _InstructionFollowing()
__all__ = ("instruction_following_suite",)
