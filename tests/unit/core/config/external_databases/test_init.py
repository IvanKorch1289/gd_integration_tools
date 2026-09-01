"""Unit-тесты ``core.config.external_databases`` — coverage ratchet (S48 W37).

core/config/external_databases/__init__.py — facade для external DB configs:
re-exports 3 Pydantic Settings classes + 1 singleton (item, connection,
registry, settings). 5 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/singleton identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.config import external_databases as ext_db
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
    ExternalDatabaseItemSettings,
    ExternalDatabasesSettings,
    external_databases_settings,
)


@pytest.mark.unit
class TestExternalDatabasesFacadeAllExports:
    """``__all__`` audit + class/singleton identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ExternalDatabaseConnectionSettings",
            "ExternalDatabaseItemSettings",
            "ExternalDatabasesSettings",
            "external_databases_settings",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(ext_db, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in ext_db.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 4 символа."""
        assert len(ext_db.__all__) == 4


@pytest.mark.unit
class TestExternalDatabasesFacadeIdentity:
    """Identity checks: 3 Settings classes + 1 singleton."""

    def test_connection_settings_is_class(self) -> None:
        """``ExternalDatabaseConnectionSettings`` — class."""
        assert isinstance(ExternalDatabaseConnectionSettings, type)

    def test_item_settings_is_class(self) -> None:
        """``ExternalDatabaseItemSettings`` — class."""
        assert isinstance(ExternalDatabaseItemSettings, type)

    def test_registry_settings_is_class(self) -> None:
        """``ExternalDatabasesSettings`` — class."""
        assert isinstance(ExternalDatabasesSettings, type)

    def test_singleton_is_registry_settings_instance(self) -> None:
        """``external_databases_settings`` — instance of ExternalDatabasesSettings."""
        assert isinstance(external_databases_settings, ExternalDatabasesSettings)
