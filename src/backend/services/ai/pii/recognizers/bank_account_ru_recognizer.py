"""Recognizer российских банковских счетов (S28 W5).

Russian bank account numbers (БИК, р/с, к/с):

* Расчётный счёт (расчётный счёт) — 20 digits ( account)
* Корреспондентский счёт — 20 digits (correspondent account)
* БИК — 9 digits (Bank Identification Code)

Format: 20-digit account number split as BBBBB CCC DDDDDDDDDD:
- B = bank's Bank ID (BIC-like, 5 digits)
- C = branch code (3 digits)
- D = account number (11 digits, can include check digits)

Context boost: "расчётный счёт", "р/с", "лицевой счёт", "счёт",
"корреспондентский счёт", "к/с", "БИК", "банковский счёт",
"номер счёта", "выставить счёт", "оплата по счёту".
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from presidio_analyzer import Pattern, PatternRecognizer

if TYPE_CHECKING:
    pass

__all__ = ("BankAccountRuRecognizer",)


class BankAccountRuRecognizer(PatternRecognizer):
    """Presidio recognizer для российских банковских счетов.

    Регистрирует entity type ``BANK_ACCOUNT_RU``. Высокий score (0.85)
    при наличии context-маркеров ("расчётный счёт", "БИК").
    """

    # 20-digit account number (Russian settlement account)
    ACCOUNT_20_PATTERN = r"\b\d{20}\b"

    # 9-digit BIC
    BIK_PATTERN = r"\b[А-ЯЁ]{1}\d{8}\b"

    # IBAN-like format for Russia (TR, not typical but found in some docs)
    # Russian accounts sometimes written with spaces: "12345 67890 12345 67890 12"
    ACCOUNT_FORMATTED_PATTERN = r"\b\d{5}\s+\d{5}\s+\d{5}\s+\d{5}\b"

    def __init__(self) -> None:
        patterns = [
            Pattern(name="ru_account_20", regex=BankAccountRuRecognizer.ACCOUNT_20_PATTERN, score=0.8),
            Pattern(name="ru_bik", regex=BankAccountRuRecognizer.BIK_PATTERN, score=0.7),
            Pattern(
                name="ru_account_formatted", regex=BankAccountRuRecognizer.ACCOUNT_FORMATTED_PATTERN, score=0.85
            ),
        ]
        super().__init__(
            supported_entity="BANK_ACCOUNT_RU",
            supported_language="ru",
            patterns=patterns,
            context=[
                "расчётный счёт",
                "р/с",
                "р.с.",
                "лицевой счёт",
                "счёт",
                "банковский счёт",
                "номер счёта",
                "счёт получателя",
                "счёт отправителя",
                "корреспондентский счёт",
                "к/с",
                "к.с.",
                "БИК",
                "бик банка",
                "выставить счёт",
                "оплата по счёту",
                "реквизиты",
                "банковские реквизиты",
            ],
        )
