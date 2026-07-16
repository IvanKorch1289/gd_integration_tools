"""Recognizer СНИЛС (Страховой Номер Индивидуального Лицевого Счёта, S218 refactor).

СНИЛС: 11 цифр формата ``XXX-XXX-XXX YY`` или ``XXXXXXXXX YY`` без разделителей.
9 серийных + 2 контрольные.

Алгоритм проверки (ПФР):
    Если серийный номер < 100,000,000 — контрольная сумма должна быть 00.
    Иначе: CS = sum(d_i × (10 − i)) mod 101, где i = 1..9, d_i — i-я цифра
    серийного номера (с единицы). Затем:

    * CS == 100 или CS == 101 → контрольная цифра 00;
    * CS < 100 → контрольная цифра = CS;
    * иначе → невалидный СНИЛС.

S218: refactored на базе :class:`RegexPiiRecognizer` + validate_result override.
"""

from __future__ import annotations

import re

from presidio_analyzer import Pattern

from src.backend.services.ai.pii.recognizers._base import RegexPiiRecognizer

__all__ = ("SnilsRecognizer",)

_DIGITS = re.compile(r"\D+")


def _snils_check_digit_valid(value: str) -> bool:
    """Возвращает True, если 11-значная строка проходит ПФР checksum."""
    digits = _DIGITS.sub("", value)
    if len(digits) != 11:
        return False
    serial = int(digits[:9])
    check = int(digits[9:])
    if serial < 100_000_000:
        return check == 0
    weighted = sum(int(digits[i]) * (9 - i) for i in range(9))
    expected: int
    cs = weighted % 101
    if cs == 100 or cs == 101:
        expected = 0
    elif cs < 100:
        expected = cs
    else:
        return False
    return expected == check


class SnilsRecognizer(RegexPiiRecognizer):
    """Presidio recognizer для СНИЛС с ПФР checksum-валидацией.

    Регистрирует entity type `SNILS_RU`. Поддерживает форматы:
    ``XXX-XXX-XXX YY``, ``XXX-XXX-XXX-YY``, ``XXX XXX XXX YY``, ``XXXXXXXXXYY``.
    """

    SUPPORTED_ENTITY = "SNILS_RU"
    PATTERNS = [
        Pattern(
            name="snils_dashed",
            regex=r"\b\d{3}[-\s]\d{3}[-\s]\d{3}[\s-]?\d{2}\b",
            score=0.5,
        ),
        Pattern(name="snils_plain", regex=r"\b\d{11}\b", score=0.3),
    ]
    CONTEXT = ["СНИЛС", "снилс", "страховой номер", "ПФР", "пенсионный"]

    def validate_result(self, pattern_text: str) -> bool:
        """Validate-hook Presidio: проверяет ПФР checksum."""
        return _snils_check_digit_valid(pattern_text)