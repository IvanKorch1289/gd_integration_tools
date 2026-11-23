"""Tests for core/enums/skb.py — тип ответа СКБ и его нормализация.

Дефект (аудит 2026-11-20): ``response_type`` из query-параметра FastAPI
разбирается в enum-член ``ResponseTypeChoices``, а сравнение enum со
строкой ``"PDF"`` даёт ``False`` → ветка «PDF» не срабатывала, и клиент,
запросивший документ, получал JSON.
"""

from __future__ import annotations


def test_response_type_choices() -> None:
    """ResponseTypeChoices: json='JSON', pdf='PDF'."""
    from src.backend.core.enums.skb import ResponseTypeChoices

    assert ResponseTypeChoices.json.value == "JSON"
    assert ResponseTypeChoices.pdf.value == "PDF"
    assert len(ResponseTypeChoices) == 2


def test_skb_module_dunder_all() -> None:
    """__all__ = ('ResponseTypeChoices', 'response_type_value')."""
    import src.backend.core.enums.skb as mod

    assert mod.__all__ == ("ResponseTypeChoices", "response_type_value")


def test_response_type_value_accepts_enum_member() -> None:
    """Enum-член приводится к строке — основа исправления PDF-ветки."""
    from src.backend.core.enums.skb import ResponseTypeChoices, response_type_value

    assert response_type_value(ResponseTypeChoices.pdf) == "PDF"
    assert response_type_value(ResponseTypeChoices.json) == "JSON"


def test_response_type_value_accepts_string_and_is_case_insensitive() -> None:
    """Строка приводится к верхнему регистру."""
    from src.backend.core.enums.skb import response_type_value

    assert response_type_value("PDF") == "PDF"
    assert response_type_value("json") == "JSON"


def test_response_type_value_accepts_object_with_value_attribute() -> None:
    """Объект с атрибутом ``value`` (как в orders-сервисе) поддерживается."""
    from src.backend.core.enums.skb import response_type_value

    fake = type("ResponseTypeChoices", (), {"value": "PDF"})()
    assert response_type_value(fake) == "PDF"


def test_response_type_value_rejects_unknown_values() -> None:
    """Неизвестные значения → None (fail-closed, не «PDF» по умолчанию)."""
    from src.backend.core.enums.skb import response_type_value

    assert response_type_value(None) is None
    assert response_type_value(42) is None
    assert response_type_value(object()) is None
