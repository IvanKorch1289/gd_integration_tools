"""S168 W17 P2-10: route_schemas для core_admin.

S168 W17 P2-10: moved from src/backend/schemas/route_schemas/admin.py
to extensions/core_admin/schemas/route.py per master prompt v8 P2-10.
core_admin is cross-cutting (admin operations on system: cache, feature
flags, route toggles) — own extension.
"""

from pydantic import Field

from src.backend.schemas.base import BaseSchema

__all__ = (
    "AdminToggleRouteQuerySchema",
    "AdminToggleFeatureFlagQuerySchema",
    "AdminCacheKeysQuerySchema",
    "AdminCacheValuePathSchema",
    "AdminCacheInvalidatePatternSchema",
    "AdminCacheInvalidateTagsSchema",
    "AdminCacheInvalidateTableSchema",
)


class AdminToggleRouteQuerySchema(BaseSchema):
    """
    Query-схема для включения и отключения маршрута.

    Attributes:
        route_path: Путь маршрута, который нужно включить или выключить.
        enable: Флаг состояния маршрута.
    """

    route_path: str = Field(
        description="Путь маршрута, который требуется включить или выключить."
    )
    enable: bool = Field(
        description="Флаг состояния маршрута: true - включить, false - выключить."
    )


class AdminToggleFeatureFlagQuerySchema(BaseSchema):
    """Query-схема для включения/отключения feature-флага."""

    flag_name: str = Field(description="Имя feature-флага.")
    enable: bool = Field(
        description="true — включить (маршруты доступны), false — отключить."
    )


class AdminCacheKeysQuerySchema(BaseSchema):
    """
    Query-схема для получения списка ключей Redis по шаблону.

    Attributes:
        pattern: Redis pattern для поиска ключей.
    """

    pattern: str = Field(default="*", description="Redis pattern для поиска ключей.")


class AdminCacheValuePathSchema(BaseSchema):
    """
    Path-схема для получения значения по ключу Redis.

    Attributes:
        key: Ключ Redis.
    """

    key: str = Field(description="Ключ Redis.")


class AdminCacheInvalidatePatternSchema(BaseSchema):
    """
    Query-схема для инвалидации кэша по glob-паттерну.

    Attributes:
        pattern: Glob pattern для поиска и удаления ключей.
    """

    pattern: str = Field(
        description="Glob pattern для инвалидации (e.g., 'entity:orders:*')."
    )


class AdminCacheInvalidateTagsSchema(BaseSchema):
    """
    Query-схема для инвалидации кэша по тегам.

    Attributes:
        tags: Список тегов для инвалидации.
    """

    tags: list[str] = Field(
        description="Список тегов для инвалидации (e.g., ['entity:orders', 'table:orders'])."
    )


class AdminCacheInvalidateTableSchema(BaseSchema):
    """
    Query-схема для инвалидации кэша по имени таблицы.

    Attributes:
        table: Имя таблицы для инвалидации.
    """

    table: str = Field(description="Имя таблицы для инвалидации (e.g., 'orders').")
