# ruff: noqa: S101
"""Sprint 16 K5-W1 — unit-тесты ``PluginGraphResolver``.

Покрытие:
    1. Линейная цепочка A → B → C — topo-порядок [A, B, C].
    2. Diamond A → {B, C} → D — A первый, D последний.
    3. Независимые плагины без зависимостей — все попадают в результат.
    4. Циклическая зависимость A → B → A — ``PluginDependencyCycleError``.
    5. Ссылка на отсутствующий плагин — ``KeyError``.
"""

from __future__ import annotations

import pytest

from src.backend.core.plugin_runtime import (
    PluginDependencyCycleError,
    PluginGraphResolver,
)
from src.backend.services.plugins.manifest_toml import (
    PluginCompatibility,
    PluginManifest,
)


def _make_manifest(
    name: str, *, requires: dict[str, str] | None = None
) -> PluginManifest:
    """Утилита: минимальный PluginManifest с заданными зависимостями.

    ``requires`` — mapping ``имя_плагина → PEP-440 spec``. Для тестов
    resolver важны только ключи (имена), spec задаётся валидный
    (``">=0.0"``) но не проверяется логикой topo-sort.
    """
    return PluginManifest(
        name=name,
        version="1.0.0",
        requires_core=">=0.2,<1.0",
        entry_class=f"extensions.{name}.plugin.Plugin",
        compatibility=PluginCompatibility(
            requires_plugins={dep: ">=0.0" for dep in (requires or {})}
        ),
    )


def test_linear_chain_orders_dependencies_first() -> None:
    """A зависит от B, B зависит от C → порядок [C, B, A]."""
    manifests = {
        "alpha": _make_manifest("alpha", requires={"beta": ">=0.0"}),
        "beta": _make_manifest("beta", requires={"gamma": ">=0.0"}),
        "gamma": _make_manifest("gamma"),
    }
    ordered = PluginGraphResolver().resolve(manifests)

    names = [m.name for m in ordered]
    assert names == ["gamma", "beta", "alpha"], names


def test_diamond_dependency_places_root_first_and_tail_last() -> None:
    """Diamond: D → B → A, D → C → A. Порядок: A первый, D последний."""
    manifests = {
        "alpha": _make_manifest("alpha"),
        "beta": _make_manifest("beta", requires={"alpha": ">=0.0"}),
        "gamma": _make_manifest("gamma", requires={"alpha": ">=0.0"}),
        "delta": _make_manifest("delta", requires={"beta": ">=0.0", "gamma": ">=0.0"}),
    }
    ordered = PluginGraphResolver().resolve(manifests)
    names = [m.name for m in ordered]

    assert names[0] == "alpha"
    assert names[-1] == "delta"
    assert set(names) == {"alpha", "beta", "gamma", "delta"}
    # beta и gamma — оба после alpha, оба до delta.
    assert names.index("beta") > 0 and names.index("beta") < names.index("delta")
    assert names.index("gamma") > 0 and names.index("gamma") < names.index("delta")


def test_independent_plugins_all_present_no_dependencies() -> None:
    """Три независимых плагина — все в результате, порядок не критичен."""
    manifests = {
        "alpha": _make_manifest("alpha"),
        "beta": _make_manifest("beta"),
        "gamma": _make_manifest("gamma"),
    }
    ordered = PluginGraphResolver().resolve(manifests)

    assert len(ordered) == 3
    assert {m.name for m in ordered} == {"alpha", "beta", "gamma"}


def test_simple_cycle_raises_plugin_dependency_cycle_error() -> None:
    """A → B → A → ``PluginDependencyCycleError`` с непустым cycle."""
    manifests = {
        "alpha": _make_manifest("alpha", requires={"beta": ">=0.0"}),
        "beta": _make_manifest("beta", requires={"alpha": ">=0.0"}),
    }
    with pytest.raises(PluginDependencyCycleError) as exc_info:
        PluginGraphResolver().resolve(manifests)

    assert exc_info.value.cycle
    assert set(exc_info.value.cycle) <= {"alpha", "beta"}
    assert "Plugin dependency cycle" in str(exc_info.value)


def test_missing_dependency_raises_keyerror() -> None:
    """A → ghost, ghost отсутствует во входе → ``KeyError``."""
    manifests = {"alpha": _make_manifest("alpha", requires={"ghost": ">=0.0"})}
    with pytest.raises(KeyError, match="ghost"):
        PluginGraphResolver().resolve(manifests)
