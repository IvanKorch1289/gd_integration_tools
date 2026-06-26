"""Schema-registry (R1, S171 M10 P2, D175).

In-memory JSON-Schema каталог для:
- LSP (Language Server Protocol) — autocomplete для DSL actions
- AsyncAPI экспорт
- OpenAPI export (если используется)
- Doc generation (schema → docs)

Ponytail (D175):
- In-memory storage + optional persistent adapter
- Версионирование через ``(name, version)`` ключ
- AsyncAPI 2.x export built-in
"""
from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

_logger = get_logger("dsl.schema_registry")

__all__ = ("SchemaRegistry", "SchemaNotFoundError")


class SchemaNotFoundError(KeyError):
    """Schema не зарегистрирована (расширенный KeyError с контекстом)."""

    def __init__(self, name: str, version: str | None = None) -> None:
        msg = f"Schema {name!r}"
        if version:
            msg += f" version={version!r}"
        msg += " not registered"
        super().__init__(msg)
        self.schema_name = name
        self.schema_version = version


class SchemaRegistry:
    """In-memory registry для JSON-Schema каталога.

    Поддерживает версионирование: одна schema name может иметь
    несколько версий (v1, v2, etc).

    Args:
        default_version: Версия по умолчанию (если не указана явно).
    """

    def __init__(self, *, default_version: str = "v1") -> None:
        self._default_version = default_version
        # Storage: name -> {version -> schema}
        self._schemas: dict[str, dict[str, dict[str, Any]]] = {}

    def register(
        self,
        name: str,
        schema: dict[str, Any],
        *,
        version: str | None = None,
    ) -> None:
        """Зарегистрировать schema.

        Args:
            name: Имя schema (например, ``order.create``).
            schema: JSON-Schema dict.
            version: Версия (default = ``default_version``).
        """
        ver = version or self._default_version
        if name not in self._schemas:
            self._schemas[name] = {}
        self._schemas[name][ver] = schema
        _logger.debug("schema.registered name=%s version=%s", name, ver)

    def unregister(self, name: str, *, version: str | None = None) -> None:
        """Удалить schema (одну версию или все)."""
        if name not in self._schemas:
            return
        if version is None:
            del self._schemas[name]
        else:
            self._schemas[name].pop(version, None)
            if not self._schemas[name]:
                del self._schemas[name]
        _logger.debug("schema.unregistered name=%s version=%s", name, version)

    def has(self, name: str, *, version: str | None = None) -> bool:
        """Проверить наличие schema."""
        if name not in self._schemas:
            return False
        if version is None:
            return bool(self._schemas[name])
        return version in self._schemas[name]

    def get(
        self, name: str, *, version: str | None = None
    ) -> dict[str, Any]:
        """Получить schema по name (и опционально version).

        Raises:
            SchemaNotFoundError: Если schema не найдена.
        """
        if name not in self._schemas:
            raise SchemaNotFoundError(name, version)
        if version is None:
            # Возвращаем default_version
            if self._default_version in self._schemas[name]:
                return self._schemas[name][self._default_version]
            # Если default нет — берём единственную версию
            versions = list(self._schemas[name].keys())
            if len(versions) == 1:
                return self._schemas[name][versions[0]]
            raise SchemaNotFoundError(
                name, f"{versions} (default={self._default_version} отсутствует)"
            )
        if version not in self._schemas[name]:
            raise SchemaNotFoundError(name, version)
        return self._schemas[name][version]

    def list_names(self) -> list[str]:
        """Список всех зарегистрированных schema names."""
        return list(self._schemas.keys())

    def list_versions(self, name: str) -> list[str]:
        """Список версий для конкретной schema."""
        return list(self._schemas.get(name, {}).keys())

    def to_asyncapi_section(self) -> dict[str, Any]:
        """Экспорт в AsyncAPI 2.x components/schemas section.

        Returns:
            Dict, готовый для встраивания в AsyncAPI document.
        """
        schemas: dict[str, dict[str, Any]] = {}
        for name, versions in self._schemas.items():
            # Берём latest version (последнюю)
            latest_ver = list(versions.keys())[-1]
            schemas[name] = versions[latest_ver]
        return {
            "components": {
                "schemas": schemas,
            },
        }
