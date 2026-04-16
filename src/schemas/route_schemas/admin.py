from pydantic import Field

from app.schemas.base import BaseSchema

__all__ = (
    "AdminToggleRouteQuerySchema",
    "AdminCacheKeysQuerySchema",
    "AdminCacheValuePathSchema",
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
