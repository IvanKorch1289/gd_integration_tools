"""Isolated DSL-route execution for plugin tests (K5 S19 W3, S-L10-1).

:class:`RouteRunner` provides a stable public interface for running DSL routes
in unit tests without a live ASGI application. It wraps the internal
:mod:`testkit._route_adapter` with a simplified signature.

Contract ( pinned by ``tests/unit/testkit_pkg/test_route_runner_contract.py`` )::

    await runner.run(route_id, payload=None, *, tenant=None) -> RouteRunResult

Example::

    runner = RouteRunner()
    result = await runner.run("my_plugin.echo", {"msg": "hello"})
    assert result.status_code == 200
    assert result.body == {"msg": "hello"}
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from testkit._route_adapter import run_route

__all__ = ("RouteRunner", "RouteRunResult")


@dataclass(slots=True, frozen=True)
class RouteRunResult:
    """Result of running a route through :class:`RouteRunner`."""

    route_id: str
    """Identifier of the executed route."""

    status_code: int
    """HTTP status code of the response (default 200 in fallback mode)."""

    body: Any
    """Response body decoded from JSON, or None."""


class RouteRunner:
    """Run DSL routes in isolation for unit tests.

    Contract: ``await runner.run(route_id, payload, tenant=None)``

    Allows tests to execute DSL routes without a live ASGI app.
    The fallback path (when no real route loader is configured) returns
    a 200 response with the payload echoed in the body.
    """

    async def run(
        self,
        route_id: str,
        payload: dict[str, Any] | None = None,
        *,
        tenant: str | None = None,
    ) -> RouteRunResult:
        """Execute a route and return a :class:`RouteRunResult`.

        Args:
            route_id: Dot-separated route identifier (e.g. ``"my_plugin.health"``).
            payload: Optional JSON-serializable request body.
            tenant: Optional tenant identifier for multi-tenant routes.

        Returns:
            RouteRunResult with route_id, status_code, and body.
        """
        result = await run_route(route_id, payload, tenant=tenant)
        return RouteRunResult(
            route_id=result.get("route_id", route_id),
            status_code=int(result.get("status_code", 200)),
            body=result.get("body"),
        )
