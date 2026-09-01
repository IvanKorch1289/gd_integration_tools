"""Unit-тесты ``core.config.base`` — coverage ratchet (S48 W36).

core/config/base/__init__.py — S65 W3 decomp facade: re-exports
AppBaseSettings + SchedulerSettings + singleton instances
(app_base_settings, scheduler_settings). 8 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + singleton
identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.config import base as config_base
from src.backend.core.config.base import (
    AppBaseSettings,
    SchedulerSettings,
    app_base_settings,
    scheduler_settings,
)


@pytest.mark.unit
class TestConfigBaseFacadeAllExports:
    """``__all__`` audit + class/singleton identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AppBaseSettings", "SchedulerSettings"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(config_base, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in config_base.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(config_base.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает S65 W3 decomp."""
        assert config_base.__doc__ is not None
        assert "S65 W3" in config_base.__doc__


@pytest.mark.unit
class TestConfigBaseFacadeIdentity:
    """Identity checks: Settings classes + singleton instances."""

    def test_app_base_settings_is_class(self) -> None:
        """``AppBaseSettings`` — class (Pydantic settings)."""
        assert isinstance(AppBaseSettings, type)

    def test_scheduler_settings_is_class(self) -> None:
        """``SchedulerSettings`` — class (Pydantic settings)."""
        assert isinstance(SchedulerSettings, type)

    def test_app_base_settings_singleton_is_settings_instance(self) -> None:
        """``app_base_settings`` — instance of AppBaseSettings."""
        assert isinstance(app_base_settings, AppBaseSettings)

    def test_scheduler_settings_singleton_is_settings_instance(self) -> None:
        """``scheduler_settings`` — instance of SchedulerSettings."""
        assert isinstance(scheduler_settings, SchedulerSettings)
