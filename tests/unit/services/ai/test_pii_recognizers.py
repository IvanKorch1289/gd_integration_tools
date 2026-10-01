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

from tests.unit.services.ai.pii.recognizers._presidio_guard import (
    skip_if_presidio_unavailable,
)

# F-W (аудит 2026-10-01): прежде стоял только ``pytest.importorskip("presidio_analyzer")``.
# Он ловит лишь ImportError, а presidio тянет torch на уровне модуля, и CUDA-сборка
# падает ValueError(libnvrtc) — модуль падал на collection и блокировал весь прогон.
#
# ВАЖНО (регрессия, пойманная на другом venv): гвард применяется к КАЖДОМУ
# подмодулю отдельно, а не к пакету-реэкспорту. Пакет
# ``src.backend.services.ai.pii.recognizers`` экспортирует только публичные
# классы (``InnRecognizer`` и т.д.), но приватные хелперы
# (``_inn_checksum_valid``, ``_snils_check_digit_valid``) живут в подмодулях
# и через пакет недоступны. Первая версия фикса обращалась к пакету —
# в окружении, где импорт падал по CUDA, это маскировалось skip'ом,
# а в venv, где presidio импортируется штатно, давало AttributeError на
# collection и снова блокировало весь прогон.
_credit = skip_if_presidio_unavailable(
    "src.backend.services.ai.pii.recognizers.credit_case_recognizer"
)
CreditCaseRecognizer = _credit.CreditCaseRecognizer

_inn = skip_if_presidio_unavailable(
    "src.backend.services.ai.pii.recognizers.inn_recognizer"
)
InnRecognizer = _inn.InnRecognizer
_inn_checksum_valid = _inn._inn_checksum_valid

_passport = skip_if_presidio_unavailable(
    "src.backend.services.ai.pii.recognizers.passport_ru_recognizer"
)
PassportRuRecognizer = _passport.PassportRuRecognizer

_snils = skip_if_presidio_unavailable(
    "src.backend.services.ai.pii.recognizers.snils_recognizer"
)
SnilsRecognizer = _snils.SnilsRecognizer
_snils_check_digit_valid = _snils._snils_check_digit_valid

# ─── INN ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,valid",
    [
        ("7707083893", True),  # ПАО Сбербанк, реальный ИНН
        ("7715228310", True),  # реальный
        ("1234567890", False),  # случайные 10 цифр
        ("0000000000", False),  # все нули
        ("9999999999", False),  # все одинаковые
        ("500100732259", True),  # 12-знач ИП, реальный
        ("123456789012", False),
        ("111111111111", False),  # все одинаковые
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
        ("000-000-001 00", True),  # serial=1<10^8 → CS=00 валидно
        ("99999999900", False),  # serial=999999999 > 10^8, CS=102 → invalid
        ("123-456-789 01", False),
        ("12345", False),  # неправильная длина
        # Round 25: edge cases на \D+ strip в _DIGITS.sub() first branch.
        ("", False),  # empty → 0 digits → len != 11
        ("   ", False),  # whitespace only → 0 digits
        ("abc-def", False),  # no digits → 0 digits
        ("①②③④⑤⑥⑦⑧⑨00", False),  # unicode digits → \D+ strips
    ],
)
def test_snils_check_digit(value: str, valid: bool) -> None:
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
    assert len(recs) == 7
    entity_types = {r.supported_entities[0] for r in recs}
    assert entity_types == {
        "INN_RU",
        "SNILS_RU",
        "PASSPORT_RU",
        "CREDIT_CASE_RU",
        "ADDRESS_RU",
        "BANK_ACCOUNT_RU",
        "DRIVER_LICENSE_RU",
    }
