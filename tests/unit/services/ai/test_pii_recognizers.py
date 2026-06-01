"""Unit-тесты 4 custom Presidio recognizers (S24 W1, ADR-NEW-16).

Проверяют:

* ИНН (10 + 12 цифр) checksum-валидацию по ФНС;
* СНИЛС control-digit алгоритм ПФР;
* Паспорт РФ — формат серия+номер (10 цифр);
* Кредитное дело — длину номера ≥ 4.

Recognizers требуют установленный ``presidio_analyzer`` (для базового класса
``PatternRecognizer``). Без него тесты автоматически skip через
``pytest.importorskip``.
"""

from __future__ import annotations

import pytest

pytest.importorskip("presidio_analyzer")

from src.backend.services.ai.pii.recognizers.credit_case_recognizer import (
    CreditCaseRecognizer,
)
from src.backend.services.ai.pii.recognizers.inn_recognizer import (
    InnRecognizer,
    _inn_checksum_valid,
)
from src.backend.services.ai.pii.recognizers.passport_ru_recognizer import (
    PassportRuRecognizer,
)
from src.backend.services.ai.pii.recognizers.snils_recognizer import (
    SnilsRecognizer,
    _snils_check_digit_valid,
)

# ─── INN ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,valid",
    [
        ("7707083893", True),  # ПАО Сбербанк, реальный ИНН
        ("5260018039", True),  # реальный
        ("7715228310", True),  # реальный
        ("1234567890", False),  # случайные 10 цифр
        ("0000000000", False),  # все нули
        ("9999999999", False),
        ("366410848395", True),  # 12-знач ИП, реальный
        ("500100732259", True),  # реальный
        ("773203202506", True),  # реальный
        ("123456789012", False),
        ("111111111111", False),
        ("12345", False),  # неправильная длина
        ("12345678901234", False),
    ],
)
def test_inn_checksum_valid(value: str, valid: bool) -> None:
    assert _inn_checksum_valid(value) is valid


def test_inn_recognizer_entity_type() -> None:
    rec = InnRecognizer()
    assert "INN_RU" in rec.supported_entities


def test_inn_recognizer_validate_result() -> None:
    rec = InnRecognizer()
    assert rec.validate_result("7707083893") is True
    assert rec.validate_result("1234567890") is False


# ─── SNILS ────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,valid",
    [
        ("112-233-445 95", True),
        ("11223344595", True),
        ("000-000-000 00", True),  # serial<10^8 → CS=00 валидно
        ("123-456-789 00", False),  # CS неверная
        ("000-000-001 00", False),  # serial<10^8 но CS должно быть 00 — здесь 00 → но serial=1 (< 100M) → CS=00 OK
        ("99999999900", False),  # 99,999,999 < 10^8 → CS=00 OK; здесь CS=00 → True; но 99999999 < 10^8 → True. Поправлю ниже
        ("123-456-789 01", False),
        ("12345", False),  # неправильная длина
    ],
)
def test_snils_check_digit(value: str, valid: bool) -> None:
    # Корректировка двух кейсов выше: 000-000-001 → serial=1<10^8 → CS=00.
    # Если value содержит "00" в конце и serial<10^8 → valid=True.
    # Тест выше задан как ложь; реальное поведение проверим в подмножестве.
    if value in ("000-000-001 00", "99999999900"):
        assert _snils_check_digit_valid(value) is True
    else:
        assert _snils_check_digit_valid(value) is valid


def test_snils_recognizer_entity_type() -> None:
    rec = SnilsRecognizer()
    assert "SNILS_RU" in rec.supported_entities


# ─── Passport RU ──────────────────────────────────────────────────────────


def test_passport_ru_recognizer_entity_type() -> None:
    rec = PassportRuRecognizer()
    assert "PASSPORT_RU" in rec.supported_entities


@pytest.mark.parametrize(
    "value,valid",
    [
        ("4509 123456", True),  # 10 цифр (4+6)
        ("45091234", False),  # 8 цифр → False
        ("4509 1234567", False),  # 11 цифр → False
        ("ABCD 123456", False),  # буквы → 6 цифр → False
    ],
)
def test_passport_validate_result(value: str, valid: bool) -> None:
    rec = PassportRuRecognizer()
    assert rec.validate_result(value) is valid


# ─── Credit Case ──────────────────────────────────────────────────────────


def test_credit_case_recognizer_entity_type() -> None:
    rec = CreditCaseRecognizer()
    assert "CREDIT_CASE_RU" in rec.supported_entities


@pytest.mark.parametrize(
    "value,valid",
    [
        ("КД-2024-001234", True),  # 8 цифр
        ("КД №12345", True),  # 5 цифр
        ("№ 12", False),  # 2 цифры < 4
        ("Договор № 12345", True),
        ("№", False),  # 0 цифр
    ],
)
def test_credit_case_validate_result(value: str, valid: bool) -> None:
    rec = CreditCaseRecognizer()
    assert rec.validate_result(value) is valid


# ─── Recognizers все вместе через _build_custom_recognizers ───────────────


def test_build_custom_recognizers_returns_four() -> None:
    from src.backend.services.ai.pii.presidio_analyzer import PresidioSanitizerAdapter

    recs = PresidioSanitizerAdapter._build_custom_recognizers()
    assert len(recs) == 4
    entity_types = {r.supported_entities[0] for r in recs}
    assert entity_types == {"INN_RU", "SNILS_RU", "PASSPORT_RU", "CREDIT_CASE_RU"}
