"""knowledge_qa suite — Q&A на финансовых документах банка (K4 S6 W1).

Reference dataset покрывает банковский домен: credit-scoring policy,
лицензионные обязательства, ставки, customer-onboarding, KYC, AML.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class _KnowledgeQA:
    """Конфигурация suite."""

    name: str = "knowledge_qa"
    description: str = "Q&A на банковских документах: KYC/AML/credit policy"

    def build_dataset(self) -> list[dict[str, Any]]:
        """Возвращает базовый dataset из 6 sample (расширяется fixture'ами)."""
        return [
            {
                "id": "kyc-1",
                "question": "Какие документы клиента нужны для KYC по 115-ФЗ?",
                "context": (
                    "По 115-ФЗ для KYC требуется паспорт РФ + ИНН + СНИЛС; "
                    "для юр. лиц — учредительные документы и доверенность."
                ),
                "expected": "паспорт ИНН СНИЛС учредительные документы",
            },
            {
                "id": "credit-1",
                "question": "Минимальный credit score для одобрения POS-кредита?",
                "context": "POS-кредит одобряется при credit score >= 600 по НБКИ.",
                "expected": "600",
            },
            {
                "id": "aml-1",
                "question": "Какая транзакция подлежит обязательному контролю?",
                "context": (
                    "По 115-ФЗ операция от 1 000 000 рублей в наличной форме "
                    "подлежит обязательному контролю."
                ),
                "expected": "1 000 000 рублей наличные",
            },
            {
                "id": "rate-1",
                "question": "Текущая ставка ЦБ РФ?",
                "context": "Ключевая ставка ЦБ РФ установлена в размере 16%.",
                "expected": "16%",
            },
            {
                "id": "onboard-1",
                "question": "Сколько занимает онбординг физлица?",
                "context": "Стандартный онбординг физлица в банке занимает 15 минут.",
                "expected": "15 минут",
            },
            {
                "id": "license-1",
                "question": "Какая лицензия требуется для платежных переводов?",
                "context": (
                    "Для оказания услуг по переводу денежных средств "
                    "необходима банковская лицензия ЦБ РФ."
                ),
                "expected": "банковская лицензия ЦБ РФ",
            },
        ]

    def score(self, sample: dict[str, Any], output: str) -> dict[str, float]:
        """Считает accuracy/recall по совпадению ключевых токенов."""
        expected = (sample.get("expected") or "").lower().split()
        actual = (output or "").lower()
        if not expected:
            return {"accuracy": 1.0}
        hit = sum(1 for token in expected if token in actual)
        accuracy = hit / max(len(expected), 1)
        return {"accuracy": float(accuracy)}


knowledge_qa_suite = _KnowledgeQA()
__all__ = ("knowledge_qa_suite",)
