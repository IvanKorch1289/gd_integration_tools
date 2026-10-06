"""Точка входа schemas-only расширения DaData.

Ранее класс был пустым и не наследовал ``BasePlugin``, из-за чего
``PluginLoader._instantiate()`` отклонял его проверкой
``isinstance(instance, BasePlugin)`` — плагин не загружался.

``BasePlugin`` не имеет абстрактных методов (все lifecycle-хуки опциональны),
поэтому достаточно объявить ``name``/``version`` из ``plugin.toml``.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backend.core.api import BasePlugin


@dataclass
class SchemasOnlyEntry(BasePlugin):
    """Точка входа расширения, содержащего только Pydantic-схемы.

    Регистрирует схемы DaData.ru geolocation API; actions/repositories/
    processors не добавляет, lifecycle-хуки — no-op.
    """

    name: str = "dadata"
    version: str = "1.0.0"
