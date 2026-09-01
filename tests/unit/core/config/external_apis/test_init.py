"""Unit-тесты ``core.config.external_apis`` — coverage ratchet (S48 W34).

core/config/external_apis/__init__.py — facade для external API configs
(Antivirus, Dadata, SKB) — re-exports Settings classes + singleton
instances. 9 statements, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity + singleton
identity.
"""

from __future__ import annotations

import pytest

from src.backend.core.config import external_apis as ext_apis
from src.backend.core.config.external_apis import (
    AntivirusAPISettings,
    DadataAPISettings,
    SKBAPISettings,
    antivirus_api_settings,
    dadata_api_settings,
    skb_api_settings,
)


@pytest.mark.unit
class TestExternalApisFacadeAllExports:
    """``__all__`` audit + class/singleton identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "AntivirusAPISettings",
            "DadataAPISettings",
            "SKBAPISettings",
            "antivirus_api_settings",
            "dadata_api_settings",
            "skb_api_settings",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(ext_apis, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in ext_apis.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 6 символов."""
        assert len(ext_apis.__all__) == 6

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает external API configs."""
        assert ext_apis.__doc__ is not None
        assert "внешних API" in ext_apis.__doc__ or "external" in ext_apis.__doc__


@pytest.mark.unit
class TestExternalApisFacadeIdentity:
    """Identity checks: settings classes + singleton instances."""

    def test_antivirus_api_settings_is_class(self) -> None:
        """``AntivirusAPISettings`` — class (Pydantic settings)."""
        assert isinstance(AntivirusAPISettings, type)

    def test_dadata_api_settings_is_class(self) -> None:
        """``DadataAPISettings`` — class (Pydantic settings)."""
        assert isinstance(DadataAPISettings, type)

    def test_skb_api_settings_is_class(self) -> None:
        """``SKBAPISettings`` — class (Pydantic settings)."""
        assert isinstance(SKBAPISettings, type)

    def test_singletons_are_settings_instances(self) -> None:
        """``*_settings`` singletons — instances соответствующих Settings."""
        assert isinstance(antivirus_api_settings, AntivirusAPISettings)
        assert isinstance(dadata_api_settings, DadataAPISettings)
        assert isinstance(skb_api_settings, SKBAPISettings)
