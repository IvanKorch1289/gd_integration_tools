"""Unit-тесты :class:`PIIMasker` (Sprint 8A K1 W4).

Покрывают:

* mask_text для 8 типов PII (email/phone/INN/SNILS/passport/card/JWT/IBAN);
* mask_dict с вложенными dict/list/tuple;
* выборочная маскировка через ``fields=...``;
* custom ``replacement``;
* стабильность ``default_masker`` singleton.
"""

# ruff: noqa: S101 — assert разрешён в pytest

from __future__ import annotations

import re

import pytest

from src.backend.core.security.pii_masker import (
    PIIMasker,
    build_default_patterns,
    default_masker,
)

# ── mask_text: 8 типов PII ──


def test_mask_text_email() -> None:
    masker = PIIMasker()
    assert masker.mask_text("Свяжись: alice@example.com") == "Свяжись: ***"


def test_mask_text_phone_ru() -> None:
    masker = PIIMasker()
    assert masker.mask_text("Тел: +7 (999) 123-45-67") == "Тел: ***"
    # E.164 короткий и без скобок
    assert masker.mask_text("call +79991234567 now") == "call *** now"


def test_mask_text_inn_10_and_12() -> None:
    masker = PIIMasker()
    assert masker.mask_text("INN org: 7707083893") == "INN org: ***"
    assert masker.mask_text("INN ind: 123456789012") == "INN ind: ***"


def test_mask_text_snils() -> None:
    masker = PIIMasker()
    assert masker.mask_text("СНИЛС: 123-456-789 12") == "СНИЛС: ***"
    assert masker.mask_text("СНИЛС: 123-456-78912") == "СНИЛС: ***"


def test_mask_text_ru_passport() -> None:
    masker = PIIMasker()
    assert masker.mask_text("Серия номер: 4509 123456") == "Серия номер: ***"


def test_mask_text_credit_card_luhn_aware() -> None:
    masker = PIIMasker()
    # Visa
    assert masker.mask_text("Карта 4111 1111 1111 1111") == "Карта ***"
    # MasterCard (16 digits, no spaces)
    assert masker.mask_text("Карта 5500000000000004") == "Карта ***"
    # American Express (15 digits)
    assert masker.mask_text("Карта 340000000000009") == "Карта ***"


def test_mask_text_jwt_bearer() -> None:
    masker = PIIMasker()
    token = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3In0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
    assert masker.mask_text(f"Authorization: Bearer {token}") == (
        "Authorization: Bearer ***"
    )


def test_mask_text_iban() -> None:
    masker = PIIMasker()
    # Немецкий и французский IBAN
    assert masker.mask_text("IBAN: DE89370400440532013000") == "IBAN: ***"
    assert masker.mask_text("IBAN: FR1420041010050500013M02606") == "IBAN: ***"


# ── mask_dict: вложенность, list, fields ──


def test_mask_dict_nested_recurses_all_strings() -> None:
    masker = PIIMasker()
    data = {
        "user": {"email": "user@example.com", "phone": "+7 999 1234567", "age": 30},
        "comment": "обычный текст без PII",
    }
    masked = masker.mask_dict(data)
    assert masked["user"]["email"] == "***"
    assert masked["user"]["phone"] == "***"
    # int не трогаем
    assert masked["user"]["age"] == 30
    # строки без PII — без изменений
    assert masked["comment"] == "обычный текст без PII"


def test_mask_dict_list_of_dicts() -> None:
    masker = PIIMasker()
    data = {
        "users": [
            {"email": "a@x.io", "name": "Анна"},
            {"email": "b@y.io", "name": "Борис"},
        ]
    }
    masked = masker.mask_dict(data)
    assert masked["users"][0]["email"] == "***"
    assert masked["users"][1]["email"] == "***"
    assert masked["users"][0]["name"] == "Анна"


def test_mask_dict_selective_fields() -> None:
    masker = PIIMasker()
    data = {
        "email": "u@x.io",
        "note": "номер +7 999 1234567 в комментарии",  # тоже PII, но не в whitelist
        "child": {"email": "n@x.io", "note": "ещё текст"},
    }
    masked = masker.mask_dict(data, fields=["email"])
    assert masked["email"] == "***"
    # note содержит phone, но т.к. fields=['email'] — он остаётся
    assert masked["note"] == "номер +7 999 1234567 в комментарии"
    # вложенный email тоже маскируется (рекурсивный обход)
    assert masked["child"]["email"] == "***"
    assert masked["child"]["note"] == "ещё текст"


def test_mask_dict_does_not_mutate_input() -> None:
    masker = PIIMasker()
    data = {"email": "x@y.io"}
    _ = masker.mask_dict(data)
    assert data == {"email": "x@y.io"}


def test_mask_dict_tuple_preserves_type() -> None:
    masker = PIIMasker()
    data: dict = {"contacts": ("a@b.c", "d@e.f", 42)}
    masked = masker.mask_dict(data)
    assert isinstance(masked["contacts"], tuple)
    assert masked["contacts"] == ("***", "***", 42)


# ── custom replacement / patterns ──


def test_custom_replacement() -> None:
    masker = PIIMasker(replacement="[REDACTED]")
    assert masker.mask_text("email a@b.c") == "email [REDACTED]"


def test_custom_patterns_only() -> None:
    """Если переданы только свои patterns — дефолтные регексы не работают."""
    only_session = {"session": re.compile(r"sid-\d+")}
    masker = PIIMasker(patterns=only_session, replacement="<sid>")
    # email НЕ маскируется (дефолтные patterns отключены).
    assert masker.mask_text("session=sid-123 email=a@b.c") == (
        "session=<sid> email=a@b.c"
    )


# ── default_masker singleton ──


def test_default_masker_is_singleton() -> None:
    a = default_masker()
    b = default_masker()
    assert a is b


def test_build_default_patterns_returns_copy() -> None:
    patterns_a = build_default_patterns()
    patterns_b = build_default_patterns()
    # Не должен возвращать один и тот же dict-инстанс
    assert patterns_a is not patterns_b
    assert set(patterns_a.keys()) == set(patterns_b.keys())


def test_empty_text_passthrough() -> None:
    masker = PIIMasker()
    assert masker.mask_text("") == ""


@pytest.mark.parametrize("value", [42, 3.14, True, None])
def test_mask_dict_non_string_scalars_unchanged(value: object) -> None:
    masker = PIIMasker()
    data = {"v": value}
    assert masker.mask_dict(data) == {"v": value}
