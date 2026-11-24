"""Property-based тест эквивалентности fast-path и полного прогона паттернов.

Аудит 2026-11-23, ЭТАП 2.2: fast-path в
``src/backend/infrastructure/observability/pii_filter.py`` пропускает пять
цифровых паттернов (SNILS, CARD, RU_PASSPORT, INN, PHONE), если в строке
нет цифр. Оптимизация даёт −0.268 ms на запрос, но её корректность
относится к типу «цифры», а ``\\d`` в Python — **Unicode**-цифра: арабские
(٠-٩), деванагари (०-९), полноширинные (０-９).

Инвариант, который проверяется: результат fast-path совпадает с
результатом полного прогона всех паттернов для любого входа.

Референс — «полный прогон»: те же паттерны, тот же порядок, но без
пропусков. Email берётся напрямую (``EMAIL.sub``), а не через
``sub_email``: так проверяется и email fast-path (ADR-0401), и цифровой.

Если property-тест когда-нибудь упадёт — fast-path небезопасен: оптимизацию
нужно откатить (ADR-0401 fast-path), а не чинить подгонкой теста.
"""

from __future__ import annotations

import re

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from src.backend.core.security.pii_patterns import (
    CARD,
    EMAIL,
    INN,
    PHONE,
    RU_PASSPORT,
    SNILS,
)
from src.backend.infrastructure.observability.pii_filter import redact_for_observability

pytestmark = pytest.mark.property

PROP = settings(
    max_examples=300, deadline=None, suppress_health_check=[HealthCheck.too_slow]
)

#: Алфавиты для генерации: ASCII + Unicode-цифры + разделители + буквы.
_ASCII_DIGITS = "0123456789"
_UNICODE_DIGITS = (
    "٠١٢٣٤٥٦٧٨٩"  # Arabic-Indic
    "०१२३४५६७८९"  # Devanagari
    "０１２３４５６７８９"  # Fullwidth
    "۰۱۲۳۴۵۶۷۸۹"  # Extended Arabic-Indic (Persian)
)
_SEPARATORS = " -+()@.,:/_\t\n"
_LETTERS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZабвгдежАБВГДЕЖ"

st_digits = st.text(alphabet=_ASCII_DIGITS, min_size=1, max_size=24)
st_unicode_digits = st.text(alphabet=_UNICODE_DIGITS, min_size=1, max_size=24)
st_any_digits = st.one_of(st_digits, st_unicode_digits)


def _full_pattern_run(value: str) -> str:
    """Референс: все паттерны безусловно, в порядке fast-path.

    Порядок повторяет ``redact_for_observability``: SNILS → CARD →
    RU_PASSPORT → INN → EMAIL → PHONE (specific-first).
    """
    v = SNILS.sub("<snils>", value)
    v = CARD.sub("<card>", v)
    v = RU_PASSPORT.sub("<passport>", v)
    v = INN.sub("<inn>", v)
    v = EMAIL.sub("<email>", v)
    v = PHONE.sub("<phone>", v)
    return v


# ── Фрагменты, из которых собирается «логовая строка» ────────────────────

st_email = st.builds(
    lambda user, host: f"{user}@{host}.com",
    st.text(alphabet="abc._+-", min_size=1, max_size=12),
    st.text(alphabet="abcdefghij", min_size=1, max_size=8),
)
st_inn = st.integers(min_value=10**9, max_value=10**12 - 1).map(str)
st_inn_unicode = st.text(alphabet=_UNICODE_DIGITS, min_size=10, max_size=12).filter(
    lambda s: len(s) in (10, 12)
)
st_snils = st.builds(
    lambda a, b, c, d: f"{a:03d}-{b:03d}-{c:03d} {d:02d}",
    st.integers(min_value=0, max_value=999),
    st.integers(min_value=0, max_value=999),
    st.integers(min_value=0, max_value=999),
    st.integers(min_value=0, max_value=99),
)
st_phone = st.builds(
    lambda p: f"+7 ({p:03d}) 123-45-67", st.integers(min_value=0, max_value=999)
)
st_date = st.dates().map(lambda d: d.isoformat())
st_card = st.text(alphabet=_ASCII_DIGITS, min_size=13, max_size=19)

st_fragment = st.one_of(
    st.text(alphabet=_LETTERS, min_size=0, max_size=16),
    st.text(alphabet=_SEPARATORS, min_size=1, max_size=4),
    st_any_digits,
    st_email,
    st_inn,
    st_inn_unicode,
    st_snils,
    st_phone,
    st_date,
    st_card,
)

st_log_line = st.lists(st_fragment, min_size=1, max_size=6).map("".join)


# ── Property: fast-path ≡ полный прогон ───────────────────────────────


@given(value=st_log_line)
@PROP
def test_fastpath_matches_full_pattern_run(value: str) -> None:
    """Результат fast-path совпадает с полным прогоном паттернов."""
    assert redact_for_observability(value) == _full_pattern_run(value)


@given(value=st.text(alphabet=_LETTERS + _SEPARATORS, min_size=0, max_size=64))
@PROP
def test_fastpath_matches_full_pattern_run_without_digits(value: str) -> None:
    """Строка без цифр: fast-path пропускает пять паттернов — результат тот же."""
    assert not re.search(r"\d", value)
    assert redact_for_observability(value) == _full_pattern_run(value)


@given(value=st_any_digits)
@PROP
def test_fastpath_matches_full_pattern_run_with_digits(value: str) -> None:
    """Строка с цифрами (в т.ч. Unicode): fast-path ничего не пропускает."""
    assert re.search(r"\d", value)
    assert redact_for_observability(value) == _full_pattern_run(value)


@given(
    value=st.text(
        alphabet=_UNICODE_DIGITS + _SEPARATORS + _LETTERS, min_size=1, max_size=40
    )
)
@PROP
def test_unicode_digits_masked_like_ascii(value: str) -> None:
    """Unicode-цифры маскируются так же, как ASCII (и тоже как полный прогон)."""
    assert redact_for_observability(value) == _full_pattern_run(value)


# ── Явные регрессии ───────────────────────────────────────────────────


def test_unicode_inn_is_masked() -> None:
    """ИНН из арабских цифр маскируется (fast-path не должен его пропустить)."""
    assert redact_for_observability("٧٧٠٧٠٨٣٨٩٣") == "<inn>"


def test_unicode_inn_12_is_masked() -> None:
    """12-значный ИНН из Unicode-цифр маскируется."""
    value = "٧٧٠٧٠٨٣٨٩٣٤٥"
    assert redact_for_observability(value) == "<inn>"


def test_unicode_snils_is_masked() -> None:
    """SNILS из Unicode-цифр маскируется."""
    assert redact_for_observability("١٢٣-٤٥٦-٧٨٩ 01") == "<snils>"


def test_unicode_phone_is_masked() -> None:
    """Телефон из Unicode-цифр маскируется."""
    assert redact_for_observability("+٧٩٠٥١٢٣٤٥٦٧") == "<phone>"


def test_digits_only_digits_still_masked() -> None:
    """Строка из одних цифр маскируется (карта/ИНН)."""
    assert redact_for_observability("4111111111111111") == "<card>"
