"""Регистрация ресурсов расширения ``core_entities_orders``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы и сервис в core-реестр, а потребители (entrypoints,
DSL) забирают их по ключу — вместо прямого импорта ``extensions.*``.

Модуль подключается динамически загрузчиком
:func:`src.backend.core.extension_registry.load_extension_resources`.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "orders"


def register() -> None:
    """Регистрирует схемы и сервис заказов в core-реестре."""
    from extensions.core_entities.orders.schemas.filter import OrderFilter
    from extensions.core_entities.orders.schemas.route import (
        OrderIdPathSchema,
        OrderIdQuerySchema,
        OrderSchemaIn,
        OrderSchemaOut,
        OrderVersionSchemaOut,
    )
    from extensions.core_entities.orders.services.orders import get_order_service

    register_extension_resource(DOMAIN, "schema", "filter", OrderFilter)
    register_extension_resource(DOMAIN, "schema", "schema_in", OrderSchemaIn)
    register_extension_resource(DOMAIN, "schema", "schema_out", OrderSchemaOut)
    register_extension_resource(
        DOMAIN, "schema", "version_schema", OrderVersionSchemaOut
    )
    register_extension_resource(DOMAIN, "schema", "id_path", OrderIdPathSchema)
    register_extension_resource(DOMAIN, "schema", "id_query", OrderIdQuerySchema)
    register_extension_resource(DOMAIN, "service", "orders", get_order_service)
