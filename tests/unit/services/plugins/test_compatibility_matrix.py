# ruff: noqa: S101
"""Sprint 14 W1 — unit-тесты ``PluginCompatibility`` и ``check_compatibility``.

Покрывает 4 ключевых кейса:

1. ``incompatible_with`` (hard) → conflict;
2. ``incompatible_plugin_specs`` (version-range) → conflict;
3. ``incompatible_core_versions`` → core_incompatible;
4. ``requires_plugins`` → missing/version-mismatch.
"""

from __future__ import annotations

import pytest

from src.backend.core.plugin_runtime.compat_checker import (
    CompatViolation,
    check_compatibility,
)
from src.backend.services.plugins.manifest_v11 import (
    PluginCompatibility,
    PluginManifestV11,
)


def _make_manifest(
    name: str, version: str, *, compatibility: PluginCompatibility | None = None
) -> PluginManifestV11:
    """Фабрика минимального манифеста для тестов."""
    return PluginManifestV11(
        name=name,
        version=version,
        requires_core=">=0.2,<1.0",
        entry_class=f"extensions.{name}.plugin.Plugin",
        compatibility=compatibility or PluginCompatibility(),
    )


class TestHardIncompatible:
    """`incompatible_with` — любая версия чужого плагина → conflict."""

    def test_hard_conflict_detected(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(incompatible_with=("beta",)),
        )
        b = _make_manifest("beta", "1.0.0")

        violations = check_compatibility([a, b])

        assert len(violations) == 1
        v = violations[0]
        assert v.plugin == "alpha"
        assert v.conflicting_plugin == "beta"
        assert v.kind == "hard_incompatible"

    def test_no_conflict_if_other_missing(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(incompatible_with=("beta",)),
        )

        violations = check_compatibility([a])

        assert violations == ()


class TestVersionIncompatible:
    """`incompatible_plugin_specs` — конфликт только в диапазоне версий."""

    def test_conflict_when_version_matches_spec(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(
                incompatible_plugin_specs={"beta": ">=0.1,<0.5"}
            ),
        )
        b = _make_manifest("beta", "0.3.0")

        violations = check_compatibility([a, b])

        kinds = {v.kind for v in violations}
        assert "version_incompatible" in kinds

    def test_no_conflict_when_version_outside_spec(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(
                incompatible_plugin_specs={"beta": ">=0.1,<0.5"}
            ),
        )
        b = _make_manifest("beta", "1.0.0")

        violations = check_compatibility([a, b])

        assert violations == ()


class TestCoreIncompatible:
    """`incompatible_core_versions` дополняет ``requires_core``."""

    def test_core_conflict_detected(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(incompatible_core_versions=">=0.5,<0.6"),
        )

        violations = check_compatibility([a], core_version="0.5.3")

        assert len(violations) == 1
        v = violations[0]
        assert v.kind == "core_incompatible"
        assert v.conflicting_plugin == "<core>"

    def test_core_compatible_pass(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(incompatible_core_versions=">=0.5,<0.6"),
        )

        violations = check_compatibility([a], core_version="0.4.9")

        assert violations == ()


class TestRequiresPlugins:
    """`requires_plugins` — отсутствие или несовместимая версия зависимости."""

    def test_missing_dependency(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(requires_plugins={"beta": ">=1.0,<2.0"}),
        )

        violations = check_compatibility([a])

        assert len(violations) == 1
        assert violations[0].kind == "missing_dependency"

    def test_dependency_version_mismatch(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(requires_plugins={"beta": ">=2.0,<3.0"}),
        )
        b = _make_manifest("beta", "1.0.0")

        violations = check_compatibility([a, b])

        kinds = {v.kind for v in violations}
        assert "dependency_version_mismatch" in kinds

    def test_dependency_satisfied(self) -> None:
        a = _make_manifest(
            "alpha",
            "1.0.0",
            compatibility=PluginCompatibility(requires_plugins={"beta": ">=1.0,<2.0"}),
        )
        b = _make_manifest("beta", "1.5.0")

        violations = check_compatibility([a, b])

        assert violations == ()


class TestInvalidSpecs:
    """Pydantic-валидация невалидных PEP-440 specifier'ов."""

    def test_invalid_incompatible_plugin_spec_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid PEP-440"):
            PluginCompatibility(incompatible_plugin_specs={"x": "not_a_specifier"})

    def test_invalid_core_spec_raises(self) -> None:
        with pytest.raises(ValueError, match="incompatible_core_versions"):
            PluginCompatibility(incompatible_core_versions="garbage!!")


def test_compat_violation_is_dataclass() -> None:
    """`CompatViolation` инстанцируется и сериализуется как dataclass."""
    v = CompatViolation(
        plugin="alpha",
        conflicting_plugin="beta",
        kind="hard_incompatible",
        reason="test",
    )
    assert v.plugin == "alpha"
    assert v.kind == "hard_incompatible"
