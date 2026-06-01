"""multi_turn_coherence suite — последовательные turns (K4 S6 W1).

Проверяет, сохраняется ли контекст между turn-ами (пример: клиент задаёт
вопрос, потом уточняющий, потом third-turn). Метрика ``coherence`` —
доля turn-ов, где LLM сохранил referent (упомянутый раньше факт).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _MultiTurnCoherence:
    name: str = "multi_turn_coherence"
    description: str = "Сохранение контекста в multi-turn диалоге"

    def build_dataset(self) -> list[dict[str, Any]]:
        return [
            {
                "id": "mt-1",
                "turns": [
                    "У меня есть карта Premium.",
                    "Какой по ней cashback?",
                    "А есть лимит?",
                ],
                "expected_referents": ["Premium", "cashback", "лимит"],
                "expected": "По Premium cashback 5%, лимит 300 000 в месяц.",
            },
            {
                "id": "mt-2",
                "turns": ["Я ИП, открыт РКО.", "Какие тарифы доступны?"],
                "expected_referents": ["ИП", "РКО", "тариф"],
                "expected": "Для ИП доступен тариф РКО Стандарт за 990 руб/мес.",
            },
            {
                "id": "mt-3",
                "turns": [
                    "Подал заявку на ипотеку.",
                    "Когда будет ответ?",
                    "А что нужно из документов?",
                ],
                "expected_referents": ["ипотек", "ответ", "документ"],
                "expected": (
                    "Ответ по ипотеке за 3 рабочих дня; "
                    "из документов нужны паспорт, справка 2-НДФЛ."
                ),
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        referents = [r.lower() for r in sample.get("expected_referents") or []]
        text = (output or "").lower()
        if not referents:
            return {"coherence": 1.0}
        hit = sum(1 for r in referents if r in text)
        return {"coherence": hit / len(referents)}


multi_turn_coherence_suite = _MultiTurnCoherence()
__all__ = ("multi_turn_coherence_suite",)
