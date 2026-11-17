"""Регистрация ресурсов расширения ``core_entities_orderkinds``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы и сервис в core-реестр, а потребители (entrypoints,
DSL) забирают их по ключу — вместо прямого импорта ``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "orderkinds"


def register() -> None:
    """Регистрирует схемы и сервис видов запросов в core-реестре."""
    from extensions.core_entities.orderkinds.schemas.filter import OrderKindFilter
    from extensions.core_entities.orderkinds.schemas.route import (
        OrderKindSchemaIn,
        OrderKindSchemaOut,
        OrderKindVersionSchemaOut,
    )
    from extensions.core_entities.orderkinds.services.orderkinds import (
        get_order_kind_service,
    )

    register_extension_resource(DOMAIN, "schema", "filter", OrderKindFilter)
    register_extension_resource(DOMAIN, "schema", "schema_in", OrderKindSchemaIn)
    register_extension_resource(DOMAIN, "schema", "schema_out", OrderKindSchemaOut)
    register_extension_resource(
        DOMAIN, "schema", "version_schema", OrderKindVersionSchemaOut
    )
    register_extension_resource(DOMAIN, "service", "orderkinds", get_order_kind_service)
