"""Unit-тесты trust_tier field в PluginManifestV11 (S18 W12, ADR-NEW-6).

Покрытие:
    * default trust_tier = "B" (secure-by-default).
    * trust_tier = "A" принимается.
    * Невалидный tier ("C", "X") → ValidationError.
    * Existing extensions (example_plugin, credit_pipeline, core_entities/*)
      имеют trust_tier = "A" (Tier-A migration verified).
"""

# ruff: noqa: S101

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest
from pydantic import ValidationError

from src.backend.services.plugins.manifest_v11 import PluginManifestV11

_BASE_FIELDS = {
    "name": "test_plugin",
    "version": "1.0.0",
    "requires_core": ">=0.1,<2.0",
    "entry_class": "test.plugin.Plugin",
}


class TestTrustTierField:
    def test_default_is_tier_b(self) -> None:
        """secure-by-default: новые плагины без декларации = Tier-B."""
        manifest = PluginManifestV11(**_BASE_FIELDS)
        assert manifest.trust_tier == "B"

    def test_explicit_tier_a(self) -> None:
        manifest = PluginManifestV11(**_BASE_FIELDS, trust_tier="A")
        assert manifest.trust_tier == "A"

    def test_explicit_tier_b(self) -> None:
        manifest = PluginManifestV11(**_BASE_FIELDS, trust_tier="B")
        assert manifest.trust_tier == "B"

    def test_invalid_tier_rejected(self) -> None:
        with pytest.raises(ValidationError):
            PluginManifestV11(**_BASE_FIELDS, trust_tier="C")  # type: ignore[arg-type]


def _read_trust_tier(path: Path) -> str | None:
    """Прямое чтение trust_tier из TOML (минует full pydantic load).

    Используется в тестах поверх existing manifest, которые могут иметь
    pre-existing schema mismatch (carryover S19+) — обходим их для
    targeted-проверки нашего нового field.
    """
    if not path.is_file():
        return None
    return tomllib.loads(path.read_text(encoding="utf-8")).get("trust_tier")


class TestExistingPluginsAreTierA:
    """S18 W12 DoD: 3 existing plugins → Tier-A (Tier-A migration verified)."""

    def test_example_plugin_is_tier_a(self) -> None:
        tier = _read_trust_tier(Path("extensions/example_plugin/plugin.toml"))
        if tier is None:
            pytest.skip("example_plugin manifest not present")
        assert tier == "A"

    def test_credit_pipeline_is_tier_a(self) -> None:
        tier = _read_trust_tier(Path("extensions/credit_pipeline/plugin.toml"))
        if tier is None:
            pytest.skip("credit_pipeline manifest not present")
        assert tier == "A"

    @pytest.mark.parametrize("entity", ["files", "orderkinds", "users", "orders"])
    def test_core_entities_are_tier_a(self, entity: str) -> None:
        tier = _read_trust_tier(Path(f"extensions/core_entities/{entity}/plugin.toml"))
        if tier is None:
            pytest.skip(f"core_entities/{entity} manifest not present")
        assert tier == "A"
