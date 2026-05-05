"""Spring Integration-style компоненты: Messaging Gateway, Interceptors,
Route Versioning.

Часть фазы C2. Публичный API:

* `MessagingGateway` — typed Python-фасад, превращает Python-функцию в
  декларативный DSL-route (подобие Spring @Gateway).
* `ChannelInterceptor` — pre/post-send hooks для route.
* `VersionedRoute` — параллельное существование v1/v2 маршрута с
  отдельной конфигурацией deprecation-headers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

__all__ = ("MessagingGateway", "ChannelInterceptor", "VersionedRoute")


@dataclass(slots=True)
class MessagingGateway:
    """Typed фасад для вызова route из Python-кода.

    Пример::

        orders_gateway = MessagingGateway(route_id="orders.create")
        result = await orders_gateway.invoke({"order_id": 1})
    """

    route_id: str

    async def invoke(
        self, payload: dict[str, Any], headers: dict[str, str] | None = None
    ) -> Any:
        from src.backend.dsl.service import get_dsl_service

        dsl = get_dsl_service()
        return await dsl.dispatch(
            route_id=self.route_id, body=payload, headers=headers or {}
        )


@dataclass(slots=True)
class ChannelInterceptor:
    """Pre/post-send hook для DSL-канала (route).

    `pre_send` и `post_send` — корутины, получающие (route_id, payload,
    headers) и возвращающие (возможно изменённые) payload/headers.
    """

    pre_send: Callable[..., Awaitable[Any]] | None = None
    post_send: Callable[..., Awaitable[Any]] | None = None


@dataclass(slots=True)
class VersionedRoute:
    """Параллельное существование v1/v2 route."""

    base_id: str
    versions: dict[str, str]  # "v1" → route_id "v2" → route_id
    deprecated: set[str] = None  # type: ignore[assignment]
    sunset_dates: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.deprecated is None:
            self.deprecated = set()
        if self.sunset_dates is None:
            self.sunset_dates = {}

    def resolve(self, version: str) -> str:
        return self.versions[version]

    def is_deprecated(self, version: str) -> bool:
        return version in self.deprecated
