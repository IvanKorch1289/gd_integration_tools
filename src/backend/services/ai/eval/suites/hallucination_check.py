"""hallucination_check suite — поиск fabricated facts в RAG-ответах (K4 S6 W1).

Каждый sample содержит контекст и эталонный ответ; metric ``faithfulness``
оценивает совпадение токенов output с контекстом, ``fabrication_rate`` —
долю токенов output отсутствующих в контексте.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True, slots=True)
class _HallucinationCheck:
    name: str = "hallucination_check"
    description: str = "Fabrication detection в RAG-ответах через context overlap"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "halluc-1",
                "context": (
                    "Банк X основан в 1995 году в Москве, "
                    "имеет генеральную лицензию ЦБ РФ № 1234."
                ),
                "question": "Когда основан Банк X?",
                "expected": "Банк X основан в 1995 году",
            },
            {
                "id": "halluc-2",
                "context": (
                    "Депозит «Доходный» имеет ставку 12% годовых при сроке от 6 месяцев."
                ),
                "question": "Какая ставка по депозиту Доходный?",
                "expected": "12% годовых",
            },
            {
                "id": "halluc-3",
                "context": "POS-кредит выдаётся на срок от 3 до 24 месяцев.",
                "question": "Максимальный срок POS-кредита?",
                "expected": "24 месяцев",
            },
            {
                "id": "halluc-4",
                "context": "Комиссия за перевод СБП — 0% до 100 000 рублей в месяц.",
                "question": "Какая комиссия СБП до 100 000 руб?",
                "expected": "0%",
            },
            {
                "id": "halluc-5",
                "context": (
                    "Карта Premium имеет cashback 5% на категории "
                    "АЗС/рестораны и 1% на остальное."
                ),
                "question": "Какой cashback на АЗС у карты Premium?",
                "expected": "5%",
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        context = sample.get("context") or ""
        ctx_tokens = {t.lower() for t in _TOKEN_RE.findall(context)}
        out_tokens = [t.lower() for t in _TOKEN_RE.findall(output or "")]
        if not out_tokens:
            return {"faithfulness": 0.0, "fabrication_rate": 0.0}
        grounded = sum(1 for t in out_tokens if t in ctx_tokens)
        fabricated = len(out_tokens) - grounded
        return {
            "faithfulness": grounded / len(out_tokens),
            "fabrication_rate": fabricated / len(out_tokens),
        }


hallucination_check_suite = _HallucinationCheck()
__all__ = ("hallucination_check_suite",)
