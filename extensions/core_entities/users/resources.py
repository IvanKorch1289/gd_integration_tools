"""Регистрация ресурсов расширения ``core_entities_users``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы, сервис и ORM-модель в core-реестр, а потребители
(entrypoints, DSL, сервисы) забирают их по ключу — вместо прямого импорта
``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "users"


def register() -> None:
    """Регистрирует схемы, сервис и модель пользователей в core-реестре."""
    from extensions.core_entities.users.domain.models import User
    from extensions.core_entities.users.schemas.filter import UserFilter
    from extensions.core_entities.users.schemas.route import (
        UserSchemaIn,
        UserSchemaOut,
        UserVersionSchemaOut,
    )
    from extensions.core_entities.users.services.users import get_user_service

    register_extension_resource(DOMAIN, "schema", "filter", UserFilter)
    register_extension_resource(DOMAIN, "schema", "schema_in", UserSchemaIn)
    register_extension_resource(DOMAIN, "schema", "schema_out", UserSchemaOut)
    register_extension_resource(
        DOMAIN, "schema", "version_schema", UserVersionSchemaOut
    )
    register_extension_resource(DOMAIN, "service", "users", get_user_service)
    register_extension_resource(DOMAIN, "model", "user", User)
