"""Sprint 16 K5-W1 — topo-sort bootstrap-порядка плагинов.

Назначение:
    Дополняет :mod:`compat_checker` (попарные конфликты + missing-deps)
    детерминированной сортировкой плагинов по DAG зависимостей
    ``compatibility.requires_plugins``. Гарантирует, что плагин-B
    инициализируется только после плагина-A, на который он ссылается.
    Циклы детектируются на этапе bootstrap, до ``on_load``.

Алгоритм:
    Используется :class:`graphlib.TopologicalSorter` (stdlib Python
    3.9+, mature, ``CycleError`` для циклов). Для каждого manifest
    добавляется узел с предками = имена из ``requires_plugins``.
    ``static_order`` возвращает плагины в порядке «зависимости
    первыми».

Контракт:
    * Вход: ``dict[name, PluginManifest]`` — уже отфильтрованный по
      ``enabled``/``feature-flag``/``compat_blocked``;
    * Выход: ``tuple[PluginManifest, ...]`` в bootstrap-порядке;
    * ``PluginDependencyCycleError`` — циклическая зависимость;
    * ``KeyError`` — ``requires_plugins`` указывает на плагин, которого
      нет во входном словаре (compat_checker должен такие случаи
      ловить заранее, но resolver защитный layer).

Связанные ADR: ADR-042 (V11 манифест), ADR-043 (capability-gate),
PLAN.md V22 раздел Sprint 16 (L8-P1-1).
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from src.backend.services.plugins.manifest_toml import PluginManifest

__all__ = ("PluginDependencyCycleError", "PluginGraphResolver")


class PluginDependencyCycleError(RuntimeError):
    """Циклическая зависимость между плагинами обнаружена на bootstrap.

    Attributes:
        cycle: Кортеж имён плагинов в порядке цикла, как его вернул
            :class:`graphlib.CycleError`. Может быть пустым, если SDK
            не передал детали.
    """

    def __init__(self, cycle: tuple[str, ...]) -> None:
        self.cycle = cycle
        path = " -> ".join(cycle) if cycle else "<unknown>"
        super().__init__(f"Plugin dependency cycle: {path}")


class PluginGraphResolver:
    """Строит DAG из ``requires_plugins`` и возвращает bootstrap-порядок.

    Stateless — допускает многократное переиспользование одного
    инстанса, безопасно в конкурентных сценариях (graphlib-сортировщик
    создаётся локально на каждый вызов :meth:`resolve`).
    """

    def resolve(
        self, manifests: Mapping[str, PluginManifest]
    ) -> tuple[PluginManifest, ...]:
        """Сортирует плагины по dependency-графу.

        Args:
            manifests: Отображение ``name → manifest`` уже
                отфильтрованного множества плагинов (без
                ``compat_blocked``/``disabled``/``feature-off``).

        Returns:
            Кортеж манифестов в bootstrap-порядке: зависимости идут
            раньше зависимых. Порядок среди узлов одного уровня —
            стабильный (определяется внутренней реализацией
            :class:`TopologicalSorter`).

        Raises:
            PluginDependencyCycleError: Граф содержит цикл.
            KeyError: ``manifest.requires_plugins`` ссылается на имя,
                которого нет в ``manifests``.
        """
        sorter: TopologicalSorter[str] = TopologicalSorter()
        for name, manifest in manifests.items():
            deps = tuple(manifest.compatibility.requires_plugins.keys())
            for dep in deps:
                if dep not in manifests:
                    raise KeyError(
                        f"Plugin {name!r} requires {dep!r}, but it is not "
                        f"present in the resolver input"
                    )
            sorter.add(name, *deps)

        try:
            order = tuple(sorter.static_order())
        except CycleError as exc:
            cycle: tuple[str, ...] = ()
            if len(exc.args) > 1 and isinstance(exc.args[1], (list, tuple)):
                cycle = tuple(str(item) for item in exc.args[1])
            raise PluginDependencyCycleError(cycle) from exc

        return tuple(manifests[name] for name in order)
