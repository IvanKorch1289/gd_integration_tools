"""Tests for core/enums/skb.py (S97 — coverage push).

ResponseTypeChoices: json, pdf — pure Enum.
"""

from __future__ import annotations


def test_response_type_choices() -> None:
    """ResponseTypeChoices: json='JSON', pdf='PDF'."""
    from src.backend.core.enums.skb import ResponseTypeChoices

    assert ResponseTypeChoices.json.value == "JSON"
    assert ResponseTypeChoices.pdf.value == "PDF"
    assert len(ResponseTypeChoices) == 2


def test_skb_module_dunder_all() -> None:
    """__all__ = ('ResponseTypeChoices',)."""
    import src.backend.core.enums.skb as mod

    assert mod.__all__ == ("ResponseTypeChoices",)
