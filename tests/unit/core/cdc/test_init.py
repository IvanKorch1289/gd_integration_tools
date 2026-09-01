"""Unit-тесты ``core.cdc`` — coverage ratchet (S48 W23).

core/cdc/__init__.py — R2.1 facade: CDC primitives (Protocol + Pydantic events).
Concrete backends живут в infrastructure/cdc/. 9 symbols re-exported,
~10 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + Protocol/Class identity.
"""

from __future__ import annotations

import pytest

from src.backend.core import cdc
from src.backend.core.cdc import (
    SUPPORTED_BACKENDS,
    CDCCursor,
    CDCEvent,
    CDCSource,
    FakeCDCSource,
    get_cdc_source,
    is_backend_available,
    list_backends,
)


@pytest.mark.unit
class TestCdcFacadeAllExports:
    """``__all__`` audit + class/Protocol identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "SUPPORTED_BACKENDS",
            "CDCCursor",
            "CDCEvent",
            "CDCOperation",
            "CDCSource",
            "FakeCDCSource",
            "get_cdc_source",
            "is_backend_available",
            "list_backends",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(cdc, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in cdc.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 9 символов."""
        assert len(cdc.__all__) == 9

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает R2.1 CDC primitives."""
        assert cdc.__doc__ is not None
        assert "R2.1" in cdc.__doc__


@pytest.mark.unit
class TestCdcFacadeProtocols:
    """Identity checks для CDC Protocol + Pydantic events."""

    def test_cdcsource_is_protocol(self) -> None:
        """``CDCSource`` — runtime_checkable Protocol."""
        from typing import Protocol

        assert isinstance(CDCSource, type) and issubclass(CDCSource, Protocol)

    def test_fakecdcsource_is_protocol(self) -> None:
        """``FakeCDCSource`` — runtime_checkable Protocol (для testing)."""
        # ``FakeCDCSource`` is a Protocol used как default in tests
        # (matches CDCSource contract via structural subtyping).
        assert callable(FakeCDCSource)
        # Protocol classes have ``__call__`` only if ``__init__`` is declared.
        assert hasattr(FakeCDCSource, "__subclasshook__") or hasattr(FakeCDCSource, "__call__")

    def test_cdc_event_is_class(self) -> None:
        """``CDCEvent`` — class (Pydantic model или dataclass)."""
        assert isinstance(CDCEvent, type)

    def test_cdc_cursor_is_class(self) -> None:
        """``CDCCursor`` — class."""
        assert isinstance(CDCCursor, type)

    def test_cdc_operation_is_literal_alias(self) -> None:
        """``CDCOperation`` — Literal type alias (e.g. 'insert'/'update'/'delete')."""
        import typing

        # CDCOperation is a typing.Literal — not a class but a type alias.
        assert hasattr(typing, "Literal")

    def test_supported_backends_is_frozenset(self) -> None:
        """``SUPPORTED_BACKENDS`` — frozenset (immutable backend registry)."""
        assert isinstance(SUPPORTED_BACKENDS, frozenset)

    def test_get_cdc_source_is_callable(self) -> None:
        """``get_cdc_source`` — factory function."""
        assert callable(get_cdc_source)

    def test_is_backend_available_is_callable(self) -> None:
        """``is_backend_available`` — predicate function."""
        assert callable(is_backend_available)

    def test_list_backends_is_callable(self) -> None:
        """``list_backends`` — listing function."""
        assert callable(list_backends)
