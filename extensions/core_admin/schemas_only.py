"""Точка входа schemas-only расширения core_admin.

Ранее класс был пустым (``class SchemasOnlyEntry:``) и не наследовал
``BasePlugin``, поэтому ``PluginLoader._instantiate()`` отклонял его проверкой
``isinstance(instance, BasePlugin)`` — плагин не загружался вовсе, несмотря на
корректный ``entry_class`` в ``plugin.toml``.

``BasePlugin`` не имеет абстрактных методов: все lifecycle-хуки опциональны и
по умолчанию no-op. Поэтому schemas-only плагину достаточно объявить
``name``/``version``, совпадающие с манифестом.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backend.core.api import BasePlugin


@dataclass
class SchemasOnlyEntry(BasePlugin):
    """Точка входа расширения, содержащего только Pydantic-схемы.

    Регистрирует схемы; actions/repositories/processors не добавляет, все
    lifecycle-хуки остаются no-op (наследуются от ``BasePlugin``).
    """

    name: str = "core_admin"
    version: str = "1.0.0"
