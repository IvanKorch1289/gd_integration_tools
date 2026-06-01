# ruff: noqa: S101
"""Sprint 14 W1 — marker-тест для ``core.plugin_runtime.compat_checker``.

Полный набор кейсов покрыт в
:mod:`tests/unit/services/plugins/test_compatibility_matrix.py`; этот
файл существует, чтобы план S14 K5 W4 не показывал «missing file» по
ожидаемому пути (``tests/unit/core/plugin_runtime/test_compat_checker.py``),
и одновременно проверяет:

* модуль импортируется по нативному pkg-пути после ``cleanup-a``
  (без ``importlib.util`` хака);
* ``check_compatibility`` остаётся публичным API (re-export).
"""

from __future__ import annotations

from src.backend.core.plugin_runtime import compat_checker
from src.backend.core.plugin_runtime.compat_checker import (
    CompatViolation,
    PluginConflictError,
    check_compatibility,
)
from src.backend.services.plugins.manifest_v11 import (
    PluginCompatibility,
    PluginManifestV11,
)


def _make_manifest(
    name: str,
    version: str,
    *,
    compatibility: PluginCompatibility | None = None,
) -> PluginManifestV11:
    return PluginManifestV11(
        name=name,
        version=version,
        requires_core=">=0.2,<1.0",
        entry_class=f"extensions.{name}.plugin.Plugin",
        compatibility=compatibility or PluginCompatibility(),
    )


def test_module_public_api_reexport() -> None:
    """``__all__`` совпадает с импортируемыми публичными символами."""
    assert "check_compatibility" in compat_checker.__all__
    assert "CompatViolation" in compat_checker.__all__
    assert "PluginConflictError" in compat_checker.__all__
    assert callable(check_compatibility)
    assert issubclass(PluginConflictError, RuntimeError)


def test_check_compatibility_detects_missing_dependency() -> None:
    """`requires_plugins` → плагин-зависимость отсутствует → violation."""
    a = _make_manifest(
        "alpha",
        "1.0.0",
        compatibility=PluginCompatibility(
            requires_plugins={"beta": ">=1.0,<2.0"},
        ),
    )
    violations = check_compatibility([a])

    assert len(violations) == 1
    v = violations[0]
    assert isinstance(v, CompatViolation)
    assert v.plugin == "alpha"
    assert v.conflicting_plugin == "beta"
    assert v.kind == "missing_dependency"


def test_check_compatibility_no_violations_in_clean_set() -> None:
    """Два независимых плагина без compatibility-деклараций → ()."""
    a = _make_manifest("alpha", "1.0.0")
    b = _make_manifest("beta", "2.0.0")
    assert check_compatibility([a, b]) == ()
