"""Runtime contract tests for the infrastructure provider facade."""

from __future__ import annotations

import pytest

from src.backend.core.di.providers import infrastructure_facade


@pytest.mark.unit
def test_all_exported_symbols_are_available() -> None:
    missing = [
        symbol
        for symbol in infrastructure_facade.__all__
        if not hasattr(infrastructure_facade, symbol)
    ]

    assert not missing, f"Missing infrastructure facade exports: {missing}"
