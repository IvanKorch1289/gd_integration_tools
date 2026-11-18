"""Регистрация ресурсов расширения ``core_entities_files``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свои схемы и сервис в core-реестр, а потребители (entrypoints,
сервисы) забирают их по ключу — вместо прямого импорта ``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "files"


def register() -> None:
    """Регистрирует схемы, сервис и admin-view файлов в core-реестре."""
    from extensions.core_entities.files.schemas.filter import FileFilter
    from extensions.core_entities.files.schemas.route import (
        FileSchemaIn,
        FileSchemaOut,
        FileVersionSchemaOut,
    )
    from extensions.core_entities.files.services.files import get_file_service

    register_extension_resource(DOMAIN, "schema", "filter", FileFilter)
    register_extension_resource(DOMAIN, "schema", "schema_in", FileSchemaIn)
    register_extension_resource(DOMAIN, "schema", "schema_out", FileSchemaOut)
    register_extension_resource(
        DOMAIN, "schema", "version_schema", FileVersionSchemaOut
    )
    register_extension_resource(DOMAIN, "service", "files", get_file_service)
    # Admin-view: ``sqladmin`` может отсутствовать в окружении — тогда
    # панель не поднимается, но остальные ресурсы домена остаются.
    try:
        from extensions.core_entities.files.admin import FileAdmin, OrderFileAdmin
    except ImportError:  # pragma: no cover — sqladmin не установлен
        pass
    else:
        register_extension_resource(DOMAIN, "admin", "file", FileAdmin)
        register_extension_resource(DOMAIN, "admin", "order_file", OrderFileAdmin)
