"""W25.3 — Migration framework для DSL-spec'ов.

Контракт:

* ``apiVersion`` — строка-дискриминатор ``v0`` / ``v1`` / ``v2``.
* Каждая миграция реализует ``DSLMigration`` (Protocol) с ``from_version``,
  ``to_version`` и ``migrate(spec) -> spec``.
* ``MigrationRegistry`` хранит все миграции и умеет искать путь
  через топологию рёбер ``(from, to)``.
* ``apply_migrations(spec, target_version, registry)`` последовательно
  применяет миграции до достижения целевой версии.

Этот модуль не привязан к runtime-Pipeline: работает только с dict'ами,
полученными из YAML/JSON. Это позволяет переиспользовать миграции
в CLI (без bootstrap'а ``RouteRegistry``) и в alembic-скриптах.
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Any, Protocol, runtime_checkable

__all__ = (
    "CURRENT_VERSION",
    "DEFAULT_LEGACY_VERSION",
    "DSLMigration",
    "MigrationError",
    "MigrationRegistry",
    "apply_migrations",
    "default_registry",
)

logger = logging.getLogger("dsl.versioning")

CURRENT_VERSION: str = "v2"
"""Целевая (актуальная) apiVersion для всех новых spec'ов."""

DEFAULT_LEGACY_VERSION: str = "v0"
"""apiVersion по умолчанию когда поле отсутствует в YAML."""


class MigrationError(RuntimeError):
    """Невозможно достичь целевой apiVersion."""


@runtime_checkable
class DSLMigration(Protocol):
    """Контракт одной миграции DSL-spec'а.

    Реализация — обычный класс с ``from_version`` / ``to_version`` /
    ``migrate``. См. ``migrations_v0_to_v1.py`` как пример.
    """

    from_version: str
    to_version: str

    def migrate(self, spec: dict[str, Any]) -> dict[str, Any]: ...


class MigrationRegistry:
    """Хранилище миграций с поиском пути BFS-обходом.

    Ребро = ``(from_version, to_version)`` → ``DSLMigration``. Поиск
    пути ``find_path(src, dst)`` возвращает упорядоченную цепочку
    миграций, либо пустой список — если путь существует только тогда,
    когда ``src == dst``. Иначе бросает ``MigrationError``.
    """

    def __init__(self) -> None:
        self._edges: dict[tuple[str, str], DSLMigration] = {}
        self._adjacency: dict[str, list[str]] = {}

    def register(self, migration: DSLMigration) -> None:
        """Регистрирует миграцию по её ``(from_version, to_version)``."""
        key = (migration.from_version, migration.to_version)
        if key in self._edges:
            raise ValueError(f"Migration {key[0]} → {key[1]} уже зарегистрирована.")
        self._edges[key] = migration
        self._adjacency.setdefault(migration.from_version, []).append(
            migration.to_version
        )

    def find_path(self, src: str, dst: str) -> list[DSLMigration]:
        """Возвращает цепочку миграций от ``src`` до ``dst``.

        Использует BFS по графу ``apiVersion -> apiVersion``.
        Возвращает пустой список, если ``src == dst``.

        Raises:
            MigrationError: Если путь не найден.
        """
        if src == dst:
            return []
        queue: deque[tuple[str, list[DSLMigration]]] = deque([(src, [])])
        visited: set[str] = {src}
        while queue:
            node, path = queue.popleft()
            for neighbor in self._adjacency.get(node, []):
                edge = self._edges[(node, neighbor)]
                next_path = [*path, edge]
                if neighbor == dst:
                    return next_path
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, next_path))
        raise MigrationError(f"Нет пути миграции {src} → {dst}")

    def known_versions(self) -> tuple[str, ...]:
        """Множество всех известных apiVersion'ов (источники + цели)."""
        seen: set[str] = set()
        for src, dst in self._edges:
            seen.add(src)
            seen.add(dst)
        return tuple(sorted(seen))


def apply_migrations(
    spec: dict[str, Any],
    *,
    target_version: str = CURRENT_VERSION,
    registry: MigrationRegistry | None = None,
) -> dict[str, Any]:
    """Последовательно применяет миграции до ``target_version``.

    Args:
        spec: Распарсенный YAML/JSON.
        target_version: Целевая apiVersion (по умолчанию — CURRENT_VERSION).
        registry: Реестр миграций. По умолчанию — ``default_registry``.

    Returns:
        Новый dict (исходный не мутируется).

    Raises:
        MigrationError: Если путь не найден.
    """
    registry = registry or default_registry()
    src_version = spec.get("apiVersion") or DEFAULT_LEGACY_VERSION
    if src_version == target_version:
        return _ensure_api_version(spec, target_version)
    chain = registry.find_path(src_version, target_version)
    if not chain:
        return _ensure_api_version(spec, target_version)
    current = dict(spec)
    for migration in chain:
        current = migration.migrate(dict(current))
        current["apiVersion"] = migration.to_version
        logger.info(
            "DSL migration applied: %s → %s (route=%s)",
            migration.from_version,
            migration.to_version,
            current.get("route_id"),
        )
    return _ensure_api_version(current, target_version)


def _ensure_api_version(spec: dict[str, Any], version: str) -> dict[str, Any]:
    if spec.get("apiVersion") != version:
        spec = dict(spec)
        spec["apiVersion"] = version
    return spec


_default: MigrationRegistry | None = None


def default_registry() -> MigrationRegistry:
    """Возвращает глобальный registry с предустановленными миграциями."""
    global _default
    if _default is None:
        _default = MigrationRegistry()
        from src.dsl.versioning.migrations_v0_to_v1 import V0ToV1Migration
        from src.dsl.versioning.migrations_v1_to_v2 import V1ToV2Migration

        _default.register(V0ToV1Migration())
        _default.register(V1ToV2Migration())
    return _default
