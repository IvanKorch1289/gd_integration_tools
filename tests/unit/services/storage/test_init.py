"""Unit-тесты ``services.storage`` — coverage ratchet (Post-Plan A Sprint 2).

core/storage services package facade: re-exports ``StorageFacade`` +
``get_storage_facade`` factory. ~10 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity +
DI factory registration check.
"""

from __future__ import annotations

import pytest

from src.backend.services import storage
from src.backend.services.storage import StorageFacade, get_storage_facade


@pytest.mark.unit
class TestStorageFacadeAllExports:
    """``__all__`` audit + class/function identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["StorageFacade", "get_storage_facade"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(storage, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in storage.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(storage.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает storage services package."""
        assert storage.__doc__ is not None
        assert "Storage" in storage.__doc__


@pytest.mark.unit
class TestStorageFacadeIdentity:
    """Identity checks для re-exports."""

    def test_storage_facade_is_class(self) -> None:
        """``StorageFacade`` — class (canonical facade)."""
        assert isinstance(StorageFacade, type)

    def test_get_storage_facade_is_callable(self) -> None:
        """``get_storage_facade`` — callable (DI factory)."""
        assert callable(get_storage_facade)

    def test_get_storage_facade_default_plugin(self) -> None:
        """``get_storage_facade`` default plugin='extension'."""
        import inspect

        sig = inspect.signature(get_storage_facade)
        assert "plugin" in sig.parameters
        assert sig.parameters["plugin"].default == "extension"

    def test_get_storage_facade_raises_runtime_error_when_not_registered(self) -> None:
        """``get_storage_facade`` без registered service → RuntimeError (graceful)."""
        from src.backend.core.svcs_registry import has_service

        original_has_service = has_service

        def fake_has_service(svc_type):  # noqa: ARG001
            return False

        import src.backend.core.svcs_registry as registry_module

        try:
            registry_module.has_service = fake_has_service
            with pytest.raises(RuntimeError, match="not registered"):
                get_storage_facade()
        finally:
            registry_module.has_service = original_has_service
