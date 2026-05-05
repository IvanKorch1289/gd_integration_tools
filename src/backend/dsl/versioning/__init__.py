"""W25.3 — DSL apiVersion + миграции спецификаций.

Поддерживает auto-upgrade YAML-spec'ов при загрузке: если в файле
``apiVersion: v0``, перед сборкой Pipeline'а к нему применяется
зарегистрированная цепочка миграций до текущей ``CURRENT_VERSION`` (v2).

См. ``docs/reference/dsl/versioning.md`` и ADR-034.
"""

from src.backend.dsl.versioning.migrations import (
    CURRENT_VERSION,
    DEFAULT_LEGACY_VERSION,
    DSLMigration,
    MigrationRegistry,
    apply_migrations,
    default_registry,
)

__all__ = (
    "CURRENT_VERSION",
    "DEFAULT_LEGACY_VERSION",
    "DSLMigration",
    "MigrationRegistry",
    "apply_migrations",
    "default_registry",
)
