"""Изолированный запуск DSL-route в тестах.

:class:`RouteRunner` — фасад над :mod:`testkit._route_adapter` с
удобной публичной сигнатурой ``run(route_id, payload, tenant=None)``.
Стабильность сигнатуры закреплена контракт-тестом (см.
``tests/unit/testkit/test_route_runner_contract.py``).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from testkit._route_adapter import run_route

__all__ = ("RouteRunResult", "RouteRunner")


@dataclass(slots=True, frozen=True)
class RouteRunResult:
    """Результат запуска маршрута через :class:`RouteRunner`."""

    route_id: str
    status_code: int
    body: Any


class RouteRunner:
    """Контракт: ``await runner.run(route_id, payload, tenant=None)``.

    Позволяет тестам поднимать DSL-route без живой ASGI-app.
    """

    async def run(
        self,
        route_id: str,
        payload: dict[str, Any] | None = None,
        *,
        tenant: str | None = None,
    ) -> RouteRunResult:
        """Выполнить route и вернуть :class:`RouteRunResult`."""
        result = await run_route(route_id, payload, tenant=tenant)
        return RouteRunResult(
            route_id=result.get("route_id", route_id),
            status_code=int(result.get("status_code", 200)),
            body=result.get("body"),
        )
