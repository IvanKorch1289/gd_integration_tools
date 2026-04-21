"""Банковские helper-функции (E1).

Валидаторы ИНН/КПП/БИК/ИБАН/SWIFT + business_day, Decimal money,
FX rate wrappers.
"""

from __future__ import annotations

import re
from datetime import date, timedelta
from decimal import Decimal
from typing import Iterable

__all__ = (
    "validate_inn",
    "validate_kpp",
    "validate_bic",
    "validate_iban",
    "validate_swift",
    "business_day",
    "money",
)

_INN10 = re.compile(r"^\d{10}$")
_INN12 = re.compile(r"^\d{12}$")
_KPP = re.compile(r"^\d{9}$")
_BIC = re.compile(r"^\d{9}$")
_SWIFT = re.compile(r"^[A-Z]{6}[A-Z0-9]{2}([A-Z0-9]{3})?$")


def validate_inn(inn: str) -> bool:
    if _INN10.match(inn):
        weights = (2, 4, 10, 3, 5, 9, 4, 6, 8)
        check = sum(int(inn[i]) * weights[i] for i in range(9)) % 11 % 10
        return check == int(inn[9])
    if _INN12.match(inn):
        weights1 = (7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        weights2 = (3, 7, 2, 4, 10, 3, 5, 9, 4, 6, 8)
        check1 = sum(int(inn[i]) * weights1[i] for i in range(10)) % 11 % 10
        check2 = sum(int(inn[i]) * weights2[i] for i in range(11)) % 11 % 10
        return check1 == int(inn[10]) and check2 == int(inn[11])
    return False


def validate_kpp(kpp: str) -> bool:
    return bool(_KPP.match(kpp))


def validate_bic(bic: str) -> bool:
    return bool(_BIC.match(bic))


def validate_swift(swift: str) -> bool:
    return bool(_SWIFT.match(swift.upper()))


def validate_iban(iban: str) -> bool:
    """MOD-97 проверка IBAN."""
    s = iban.replace(" ", "").upper()
    if len(s) < 5 or not s[:2].isalpha() or not s[2:4].isdigit():
        return False
    rearranged = s[4:] + s[:4]
    numeric = "".join(str(ord(c) - 55) if c.isalpha() else c for c in rearranged)
    try:
        return int(numeric) % 97 == 1
    except ValueError:
        return False


def business_day(
    current: date, *, holidays: Iterable[date] = (), weekend_days: tuple[int, ...] = (5, 6)
) -> date:
    """Следующий business day (пропускает weekend и holidays)."""
    d = current + timedelta(days=1)
    holiday_set = set(holidays)
    while d.weekday() in weekend_days or d in holiday_set:
        d += timedelta(days=1)
    return d


def money(value: str | float | int | Decimal, *, places: int = 2) -> Decimal:
    """Нормализация денежной суммы (Decimal, указанное число знаков)."""
    from decimal import ROUND_HALF_UP

    quantum = Decimal(10) ** -places
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)
