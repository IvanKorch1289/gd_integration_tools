"""Recognizer номера кредитного дела / договора (banking domain, S24 W1).

Покрывает несколько типичных форматов банковских идентификаторов:

* `КД-2024-001234` (КД + год + порядковый);
* `КД №12345/2024`;
* `Договор №К-12345`;
* `№ 12345/К` (с контекстом «кредитный», «договор»).

Поскольку формат варьируется между банками, recognizer полагается на
сильную context-зависимость («кредитное дело», «кредитный договор», «номер
договора»), а pattern-score сам по себе намеренно низкий.
"""

from __future__ import annotations

from presidio_analyzer import Pattern, PatternRecognizer

__all__ = ("CreditCaseRecognizer",)


class CreditCaseRecognizer(PatternRecognizer):
    """Presidio recognizer для номеров кредитного дела / договора.

    Регистрирует entity type `CREDIT_CASE_RU`. Default-low score —
    финальное решение принимает context similarity boost.
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(
                name="credit_case_kd_prefix",
                regex=r"\b(?:КД|кд)[\s-]*№?\s*\d{4,}(?:[/-]\d{2,4})?\b",
                score=0.5,
            ),
            Pattern(
                name="credit_case_dogovor_prefix",
                regex=r"\b(?:[ДдDd]оговор[а-яё]*)\s*№?\s*[А-ЯA-Z]?-?\d{4,}\b",
                score=0.4,
            ),
            Pattern(
                name="credit_case_number_only",
                regex=r"№\s?\d{4,}(?:[/-][А-ЯA-Zа-яa-z0-9]+)?",
                score=0.2,
            ),
        ]
        super().__init__(
            supported_entity="CREDIT_CASE_RU",
            supported_language="ru",
            patterns=patterns,
            context=[
                "кредитное дело",
                "кредитный договор",
                "договор кредита",
                "номер договора",
                "ссудный счёт",
                "ссудный счет",
                "ссудного счёта",
                "потребительский кредит",
                "ипотека",
                "автокредит",
            ],
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate-hook: длина номера ≥ 4 цифр для отсеивания шума."""
        digit_count = sum(1 for c in pattern_text if c.isdigit())
        return digit_count >= 4
