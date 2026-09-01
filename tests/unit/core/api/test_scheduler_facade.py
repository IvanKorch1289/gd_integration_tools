"""Unit-тесты ``core.api.scheduler`` — coverage ratchet (S48 W18).

core/api/scheduler.py — Sprint 38 R13 FIX facade: re-exports
``infrastructure.scheduler.dlq`` и ``scheduler_manager`` sub-modules
для lazy proxy resolution в services.scheduler.admin. 3 statements,
0% coverage.

Цель slice: 0% → 100% через __all__ audit + module identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.api import scheduler
from src.backend.core.api.scheduler import dlq, scheduler_manager


@pytest.mark.unit
class TestSchedulerFacadeAllExports:
    """``__all__`` audit + module identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["dlq", "scheduler_manager"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(scheduler, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in scheduler.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(scheduler.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Sprint 38 R13 FIX."""
        assert scheduler.__doc__ is not None
        assert "Sprint 38" in scheduler.__doc__


@pytest.mark.unit
class TestSchedulerFacadeModules:
    """Identity checks для re-exported sub-modules."""

    def test_dlq_module_has_canonical_class(self) -> None:
        """``dlq`` module содержит ``SchedulerDLQStore``."""
        assert hasattr(dlq, "SchedulerDLQStore")

    def test_scheduler_manager_module_has_canonical_class(self) -> None:
        """``scheduler_manager`` module содержит ``SchedulerManager``."""
        assert hasattr(scheduler_manager, "SchedulerManager")
