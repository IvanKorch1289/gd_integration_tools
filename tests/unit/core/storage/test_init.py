"""Unit-тесты ``core.storage`` — coverage ratchet (S48 W29).

core/storage/__init__.py — S123 W1 / S36-W23 facade: re-exports DI providers
для single entry point (``get_object_storage_provider``,
``get_storage_facade_provider``, ``set_object_storage_provider``,
``set_storage_facade_provider``) — extensions получают StorageFacade
без прямого импорта из services.storage.facade.
5 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import storage as core_storage
from src.backend.core.storage import (
    get_object_storage_provider,
    get_storage_facade_provider,
    set_object_storage_provider,
    set_storage_facade_provider,
)


@pytest.mark.unit
class TestStorageFacadeAllExports:
    """``__all__`` audit + callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "get_object_storage_provider",
            "get_storage_facade_provider",
            "set_object_storage_provider",
            "set_storage_facade_provider",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(core_storage, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in core_storage.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(core_storage.__all__) == 4

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S123 W1 / S36-W23 capability facade."""
        assert core_storage.__doc__ is not None
        assert "S123" in core_storage.__doc__ or "S36-W23" in core_storage.__doc__


@pytest.mark.unit
class TestStorageFacadeIdentity:
    """Identity checks: все 4 — DI provider functions (callable)."""

    def test_get_object_storage_provider_is_callable(self) -> None:
        """``get_object_storage_provider`` — callable."""
        assert callable(get_object_storage_provider)

    def test_get_storage_facade_provider_is_callable(self) -> None:
        """``get_storage_facade_provider`` — callable."""
        assert callable(get_storage_facade_provider)

    def test_set_object_storage_provider_is_callable(self) -> None:
        """``set_object_storage_provider`` — callable."""
        assert callable(set_object_storage_provider)

    def test_set_storage_facade_provider_is_callable(self) -> None:
        """``set_storage_facade_provider`` — callable."""
        assert callable(set_storage_facade_provider)
