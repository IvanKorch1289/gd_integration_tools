"""Регистрация ресурсов расширения ``dadata``.

ADR-0457 (инверсия зависимостей ``src/ → extensions``): расширение
**отдаёт** свою схему в core-реестр, а потребители (entrypoints, DSL)
забирают её по ключу — вместо прямого импорта ``extensions.*``.
"""

from __future__ import annotations

from src.backend.core.extension_registry import register_extension_resource

__all__ = ("DOMAIN", "register")

#: Домен ресурсов расширения.
DOMAIN = "dadata"


def register() -> None:
    """Регистрирует схему геолокации DaData в core-реестре."""
    from extensions.dadata.schemas.route import DadataGeolocateQuerySchema

    register_extension_resource(DOMAIN, "schema", "geolocate", DadataGeolocateQuerySchema)
