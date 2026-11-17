"""Регистрация ресурсов расширения ``core_admin``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы админ-эндпоинтов в core-реестр, а потребители
(entrypoints) забирают их по ключу — вместо прямого импорта ``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "core_admin"


def register() -> None:
    """Регистрирует схемы админ-эндпоинтов в core-реестре."""
    from extensions.core_admin.schemas.route import (
        AdminCacheInvalidatePatternSchema,
        AdminCacheInvalidateTableSchema,
        AdminCacheInvalidateTagsSchema,
        AdminCacheKeysQuerySchema,
        AdminCacheValuePathSchema,
        AdminToggleFeatureFlagQuerySchema,
        AdminToggleRouteQuerySchema,
    )

    register_extension_resource(
        DOMAIN, "schema", "cache_invalidate_pattern", AdminCacheInvalidatePatternSchema
    )
    register_extension_resource(
        DOMAIN, "schema", "cache_invalidate_table", AdminCacheInvalidateTableSchema
    )
    register_extension_resource(
        DOMAIN, "schema", "cache_invalidate_tags", AdminCacheInvalidateTagsSchema
    )
    register_extension_resource(
        DOMAIN, "schema", "cache_keys_query", AdminCacheKeysQuerySchema
    )
    register_extension_resource(
        DOMAIN, "schema", "cache_value_path", AdminCacheValuePathSchema
    )
    register_extension_resource(
        DOMAIN, "schema", "toggle_feature_flag", AdminToggleFeatureFlagQuerySchema
    )
    register_extension_resource(
        DOMAIN, "schema", "toggle_route", AdminToggleRouteQuerySchema
    )
