"""Unit-тесты ``infrastructure.sources`` — coverage ratchet (S49 W8).

infrastructure/sources/__init__.py — W23 source backends facade:
re-exports ``build_source`` (factory) + ``FileWatcherSource`` + ``FileEvent``.
13 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.infrastructure import sources
from src.backend.infrastructure.sources import (
    FileEvent,
    FileWatcherSource,
    build_source,
)


@pytest.mark.unit
class TestSourcesFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["FileEvent", "FileWatcherSource", "build_source"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(sources, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in sources.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(sources.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает W23 source backends."""
        assert sources.__doc__ is not None
        assert "W23" in sources.__doc__ or "source" in sources.__doc__.lower()


@pytest.mark.unit
class TestSourcesFacadeIdentity:
    """Identity checks для re-exports."""

    def test_file_event_is_class(self) -> None:
        """``FileEvent`` — class (dataclass / pydantic event)."""
        assert isinstance(FileEvent, type)

    def test_file_watcher_source_is_class(self) -> None:
        """``FileWatcherSource`` — class (filesystem watcher backend)."""
        assert isinstance(FileWatcherSource, type)

    def test_build_source_is_callable(self) -> None:
        """``build_source`` — callable (factory function)."""
        assert callable(build_source)
