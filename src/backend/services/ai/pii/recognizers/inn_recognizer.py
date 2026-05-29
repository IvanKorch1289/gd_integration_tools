"""Recognizer ИНН (10 или 12 цифр) с checksum-валидацией ФНС (S24 W1).

ИНН (Идентификационный Номер Налогоплательщика):

* Юридические лица — 10 цифр (1 контрольная);
* Физические лица / ИП — 12 цифр (2 контрольные).

Валидация по официальному алгоритму ФНС (`Приказ ФНС РФ от 29.06.2012 №ММВ-7-6/435@`):
веса [2, 4, 10, 3, 5, 9, 4, 6, 8, 0] для 10-знач формы и [7, 2, 4, 10, 3, 5, 9, 4, 6, 8, 0]
+ [3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8, 0] для 12-знач формы. Каждая контрольная цифра =
sum(d_i × w_i) mod 11 mod 10. Это позволяет отсеять случайные 10/12-значные числа.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from presidio_analyzer import Pattern, PatternRecognizer

if TYPE_CHECKING:
    pass

__all__ = ("InnRecognizer",)

_INN_10_WEIGHTS = (2, 4, 10, 3, 5, 9, 4, 6, 8, 0)
_INN_12_WEIGHTS_1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8, 0)
_INN_12_WEIGHTS_2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8, 0)


def _inn_checksum_valid(value: str) -> bool:
    """Возвращает True, если строка цифр является валидным ИНН по алгоритму ФНС.

    Поддерживает 10- и 12-знаковые формы. Все прочие длины → False.
    """
    digits = [int(c) for c in value if c.isdigit()]
    if len(digits) == 10:
        checksum = sum(d * w for d, w in zip(digits[:10], _INN_10_WEIGHTS)) % 11 % 10
        return checksum == digits[9]
    if len(digits) == 12:
        cs1 = sum(d * w for d, w in zip(digits[:11], _INN_12_WEIGHTS_1)) % 11 % 10
        cs2 = sum(d * w for d, w in zip(digits[:12], _INN_12_WEIGHTS_2)) % 11 % 10
        return cs1 == digits[10] and cs2 == digits[11]
    return False


class InnRecognizer(PatternRecognizer):
    """Presidio recognizer для ИНН с checksum-валидацией ФНС.

    Регистрирует entity type `INN_RU`. Высокий score (0.9) при валидной
    контрольной сумме, низкий (0.1) — при невалидной (фильтруется
    Presidio's score-threshold по умолчанию).
    """

    def __init__(self) -> None:
        patterns = [
            Pattern(name="inn_10_12_digits", regex=r"\b\d{10}(\d{2})?\b", score=0.4)
        ]
        super().__init__(
            supported_entity="INN_RU",
            supported_language="ru",
            patterns=patterns,
            context=["ИНН", "инн", "налогоплательщик", "налоговый"],
        )

    def validate_result(self, pattern_text: str) -> bool:
        """Validate-hook Presidio: True повышает score, False — отсеивает."""
        return _inn_checksum_valid(pattern_text)
