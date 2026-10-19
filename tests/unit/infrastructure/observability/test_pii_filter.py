"""Tests for ``src.backend.infrastructure.observability.pii_filter``.

V15 S1, W21: PII redaction для logs/spans/metrics.
Patterns: SNILS, CARD, RU_PASSPORT, INN, EMAIL, PHONE.
"""

from __future__ import annotations

from src.backend.infrastructure.observability import pii_filter as mod
from src.backend.infrastructure.observability.pii_filter import (
    mask_pii,
    redact_for_observability,
)


class TestRedactString:
    """redact_for_observability(str) — single PII redaction."""

    def test_email_redacted(self) -> None:
        result = redact_for_observability("user@example.com")
        assert result == "<email>"

    def test_phone_redacted(self) -> None:
        # +7 (905) 123-45-67
        result = redact_for_observability("+7 905 123 45 67")
        assert result == "<phone>"

    def test_snils_redacted(self) -> None:
        # XXX-XXX-XXX YY
        result = redact_for_observability("123-456-789 01")
        assert result == "<snils>"

    def test_passport_redacted(self) -> None:
        # XXXX XXXXXX (4 ws 6)
        result = redact_for_observability("1234 567890")
        assert result == "<passport>"

    def test_inn_10_redacted(self) -> None:
        result = redact_for_observability("1234567890")
        # 10 цифр подряд = INN individual
        assert result == "<inn>"

    def test_inn_12_redacted(self) -> None:
        result = redact_for_observability("123456789012")
        # 12 цифр = INN legal
        assert result == "<inn>"

    def test_card_redacted(self) -> None:
        # 16 цифр (Visa/MC)
        result = redact_for_observability("4111111111111111")
        assert result == "<card>"

    def test_no_pii_unchanged(self) -> None:
        result = redact_for_observability("hello world")
        assert result == "hello world"

    def test_empty_string(self) -> None:
        assert redact_for_observability("") == ""


class TestRedactSpecificityOrder:
    """Порядок regex'ов: SNILS (с дефисами) → CARD (13+ цифр) → PASSPORT → INN → EMAIL → PHONE."""

    def test_snils_with_dashes_not_caught_by_card(self) -> None:
        # SNILS XXX-XXX-XXX YY — содержит 11 цифр (не 13+), не должен попасть в CARD
        result = redact_for_observability("123-456-789 01")
        # Один snils, не card+inn
        assert result == "<snils>"

    def test_long_digits_card_not_inn(self) -> None:
        # 16 цифр = CARD, не INN (10/12)
        result = redact_for_observability("4111111111111111")
        assert result == "<card>"

    def test_12_digits_inn_not_card(self) -> None:
        # 12 цифр = INN legal, не CARD (13+)
        result = redact_for_observability("123456789012")
        assert result == "<inn>"


class TestRedactMultiplePIIInOneString:
    """Несколько PII в одной строке."""

    def test_email_and_phone(self) -> None:
        result = redact_for_observability("contact user@example.com or +7 905 123 45 67")
        # Оба маскируются
        assert "<email>" in result
        assert "<phone>" in result
        assert "user@example.com" not in result

    def test_no_pii_preserved(self) -> None:
        result = redact_for_observability("plain text without any")
        assert result == "plain text without any"


class TestRedactDict:
    """redact_for_observability(dict) — recursive."""

    def test_flat_dict(self) -> None:
        result = redact_for_observability({"email": "user@example.com", "name": "John"})
        assert result == {"email": "<email>", "name": "John"}

    def test_nested_dict(self) -> None:
        result = redact_for_observability(
            {"user": {"email": "a@b.com", "phone": "+7 905 123 45 67"}}
        )
        assert result == {"user": {"email": "<email>", "phone": "<phone>"}}

    def test_dict_with_non_string_values(self) -> None:
        result = redact_for_observability(
            {"count": 42, "ratio": 3.14, "enabled": True, "data": None}
        )
        # Non-string values проходят unchanged
        assert result == {"count": 42, "ratio": 3.14, "enabled": True, "data": None}


class TestRedactList:
    """redact_for_observability(list) — recursive."""

    def test_list_of_strings(self) -> None:
        result = redact_for_observability(["user@example.com", "plain"])
        assert result == ["<email>", "plain"]

    def test_nested_list_in_dict(self) -> None:
        result = redact_for_observability({"emails": ["a@b.com", "c@d.com"]})
        assert result == {"emails": ["<email>", "<email>"]}


class TestRedactTuple:
    """redact_for_observability(tuple) — recursive, returns tuple."""

    def test_tuple_redacted(self) -> None:
        result = redact_for_observability(("a@b.com", "plain"))
        assert result == ("<email>", "plain")
        assert isinstance(result, tuple)


class TestRedactNonStringTypes:
    """Non-string types проходят unchanged."""

    def test_int_unchanged(self) -> None:
        assert redact_for_observability(42) == 42

    def test_float_unchanged(self) -> None:
        assert redact_for_observability(3.14) == 3.14

    def test_bool_unchanged(self) -> None:
        assert redact_for_observability(True) is True
        assert redact_for_observability(False) is False

    def test_none_unchanged(self) -> None:
        assert redact_for_observability(None) is None


class TestMaskPii:
    """mask_pii() — structlog-processor signature."""

    def test_signature_accepted(self) -> None:
        # Совместима с structlog: (logger, method_name, event_dict)
        result = mask_pii(None, "info", {"user": "a@b.com"})
        assert result == {"user": "<email>"}

    def test_returns_new_dict(self) -> None:
        original = {"x": "a@b.com"}
        result = mask_pii(None, "info", original)
        # Возвращается новый dict
        assert result is not original

    def test_preserves_keys(self) -> None:
        result = mask_pii(None, "info", {"k1": "v1", "k2": "v2"})
        assert set(result.keys()) == {"k1", "k2"}

    def test_redacts_nested_pii(self) -> None:
        result = mask_pii(
            None,
            "info",
            {"user": {"email": "a@b.com", "name": "John"}},
        )
        assert result == {"user": {"email": "<email>", "name": "John"}}

    def test_logger_and_method_name_ignored(self) -> None:
        # _logger и _method_name не используются в логике
        r1 = mask_pii(None, "info", {"k": "v"})
        r2 = mask_pii("any-logger", "warn", {"k": "v"})
        r3 = mask_pii(object(), "error", {"k": "v"})
        # Все три возвращают одинаковый результат
        assert r1 == r2 == r3


class TestAllExports:
    """__all__ проверка."""

    def test_exports_two_functions(self) -> None:
        assert "mask_pii" in mod.__all__
        assert "redact_for_observability" in mod.__all__
        assert len(mod.__all__) == 2

    def test_functions_callable(self) -> None:
        assert callable(mask_pii)
        assert callable(redact_for_observability)


class TestModuleImport:
    """Smoke imports."""

    def test_module_imports(self) -> None:
        from src.backend.infrastructure.observability import pii_filter as m

        assert m is mod

    def test_imports_pii_patterns(self) -> None:
        # Module использует pii_patterns (S219/S222 single source of truth)
        from src.backend.core.security import pii_patterns

        assert hasattr(pii_patterns, "SNILS")
        assert hasattr(pii_patterns, "EMAIL")


class TestEdgeCases:
    """Edge cases."""

    def test_partial_pii_not_matched(self) -> None:
        # 5 цифр — не INN (10/12), не CARD (13+)
        result = redact_for_observability("12345")
        # Может быть phone match (5 цифр подряд), но не определено
        # Главное — не падает
        assert isinstance(result, str)

    def test_iso_date_not_matched_as_phone(self) -> None:
        # Regression test для fix(privacy): ISO-дата (2026-10-19) не должна
        # маскироваться как телефон. Цифры разделены дефисами, не пробелами.
        result = redact_for_observability("2026-10-19")
        assert result == "2026-10-19"
        assert "<phone>" not in result

    def test_iso_datetime_not_matched(self) -> None:
        # Полный ISO timestamp
        result = redact_for_observability("2026-10-19T14:30:00Z")
        assert result == "2026-10-19T14:30:00Z"

    def test_redact_empty_dict(self) -> None:
        assert redact_for_observability({}) == {}

    def test_redact_empty_list(self) -> None:
        assert redact_for_observability([]) == []

    def test_redact_empty_tuple(self) -> None:
        assert redact_for_observability(()) == ()