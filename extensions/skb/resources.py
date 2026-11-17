"""Регистрация ресурсов расширения ``skb``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы и resolver WAF-маршрута в core-реестр, а потребители
(entrypoints, DSL, сервисы) забирают их по ключу — вместо прямого импорта
``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "skb"


def register() -> None:
    """Регистрирует схемы СКБ и resolver WAF-маршрута в core-реестре."""
    from extensions.skb.schemas.route import (
        APISKBOrderSchemaIn,
        SKBObjectsByAddressQuerySchema,
        SKBOrdersListQuerySchema,
        SKBResultQuerySchema,
    )
    from extensions.skb.services.waf_route import resolve_waf_route

    register_extension_resource(DOMAIN, "schema", "api_skb_order_in", APISKBOrderSchemaIn)
    register_extension_resource(
        DOMAIN, "schema", "objects_by_address", SKBObjectsByAddressQuerySchema
    )
    register_extension_resource(
        DOMAIN, "schema", "orders_list", SKBOrdersListQuerySchema
    )
    register_extension_resource(DOMAIN, "schema", "result", SKBResultQuerySchema)
    register_extension_resource(DOMAIN, "service", "resolve_waf_route", resolve_waf_route)
