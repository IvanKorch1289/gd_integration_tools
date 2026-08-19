"""Recognizer российских банковских счетов (S28 W5, S218 refactor).

Russian bank account numbers (БИК, р/с, к/с):

* Расчётный счёт (расчётный счёт) — 20 digits (account)
* Корреспондентский счёт — 20 digits (correspondent account)
* БИК — 9 digits (Bank Identification Code)

Format: 20-digit account number split as BBBBB CCC DDDDDDDDDD:
- B = bank's Bank ID (BIC-like, 5 digits)
- C = branch code (3 digits)
- D = account number (11 digits, can include check digits)

Context boost: "расчётный счёт", "р/с", "лицевой счёт", "счёт",
"корреспондентский счёт", "к/с", "БИК", "банковский счёт",
"номер счёта", "выставить счёт", "оплата по счёту".

S218: refactored на базе :class:`RegexPiiRecognizer`.
"""

from __future__ import annotations

from presidio_analyzer import Pattern

from src.backend.services.ai.pii.recognizers._base import RegexPiiRecognizer

__all__ = ("BankAccountRuRecognizer",)


class BankAccountRuRecognizer(RegexPiiRecognizer):
    """Presidio recognizer для российских банковских счетов.

    Регистрирует entity type ``BANK_ACCOUNT_RU``. Высокий score (0.85)
    при наличии context-маркеров ("расчётный счёт", "БИК").
    """

    ACCOUNT_20_PATTERN = r"\b\d{20}\b"
    BIK_PATTERN = r"\b[А-ЯЁ]{1}\d{8}\b"
    ACCOUNT_FORMATTED_PATTERN = r"\b\d{5}\s+\d{5}\s+\d{5}\s+\d{5}\b"

    SUPPORTED_ENTITY = "BANK_ACCOUNT_RU"
    PATTERNS = [
        Pattern(name="ru_account_20", regex=ACCOUNT_20_PATTERN, score=0.8),
        Pattern(name="ru_bik", regex=BIK_PATTERN, score=0.7),
        Pattern(
            name="ru_account_formatted", regex=ACCOUNT_FORMATTED_PATTERN, score=0.85
        ),
    ]
    CONTEXT = [
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
    ]
