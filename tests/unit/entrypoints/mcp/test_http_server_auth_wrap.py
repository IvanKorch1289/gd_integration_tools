"""Unit-тесты ``entrypoints.mcp.http_server`` — McpAuthMiddleware wrap restoration (S49 W1).

S48 M1 W13 swarm audit (A5 Entrypoints #1): defense-in-depth потерян — McpAuthMiddleware
wrap был REMOVED из ``create_mcp_http_app()`` в cycle 217. S49 W1 fix восстановил
wrap (P0 swarm-48 backlog #19).

Этот тест проверяет:
1. ``create_mcp_http_app()`` возвращает (wrapped_app, lifespan) pair
2. wrapped_app — instance ``McpAuthMiddleware``
3. wrapped_app wraps inner_app (``_app`` attribute on middleware)
4. lifespan callable — из ``inner_app.router.lifespan_context``
"""

from __future__ import annotations

import pytest

from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware
from src.backend.entrypoints.mcp.http_server import create_mcp_http_app


@pytest.mark.unit
class TestCreateMcpHttpAppReturnsWrappedPair:
    """S49 W1: ``create_mcp_http_app()`` возвращает (wrapped, lifespan) pair."""

    def test_returns_tuple_of_two_elements(self) -> None:
        """Returns 2-element tuple (wrapped_app, lifespan)."""
        result = create_mcp_http_app()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_mcp_auth_middleware_instance(self) -> None:
        """First element — ``McpAuthMiddleware`` instance (defense-in-depth wrap)."""
        wrapped_app, _ = create_mcp_http_app()
        assert isinstance(wrapped_app, McpAuthMiddleware)

    def test_middleware_wraps_inner_app(self) -> None:
        """``McpAuthMiddleware._app`` — inner FastMCP ASGI app."""
        wrapped_app, _ = create_mcp_http_app()
        # McpAuthMiddleware stores inner app in private ``_app`` attribute.
        assert hasattr(wrapped_app, "_app")
        assert wrapped_app._app is not None

    def test_second_element_is_lifespan_callable(self) -> None:
        """Second element — lifespan context-manager function (callable)."""
        _, lifespan = create_mcp_http_app()
        assert callable(lifespan)


@pytest.mark.unit
class TestMcpAuthMiddlewareBlocksAnonymous:
    """Sanity: ``McpAuthMiddleware`` (defense layer) blocks anonymous requests.

    Reuses pattern из ``test_mcp_no_dsl_principal_propagation.py::TestMcpAuthMiddlewareBlocksAnonymous``
    чтобы подтвердить, что wrap действительно фильтрует ASGI-сообщения.
    """

    @pytest.mark.asyncio
    async def test_anonymous_request_returns_401(self) -> None:
        """HTTP scope без API_KEY/JWT → 401 (defense-in-depth active)."""
        from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

        captured: list[dict[str, object]] = []

        async def fake_send(message: dict[str, object]) -> None:
            captured.append(message)

        async def fake_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            captured.append({"type": "downstream_called"})

        middleware = McpAuthMiddleware(fake_app)
        scope = {
            "type": "http",
            "headers": [],
            "method": "POST",
            "path": "/mcp/test",
        }

        async def empty_receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        await middleware(scope, empty_receive, fake_send)

        # 401 response sent.
        assert any(
            msg.get("status") == 401
            for msg in captured
            if "status" in msg
        ), f"Expected 401, got: {captured}"
        # Downstream NOT called (auth blocked).
        assert not any(
            msg.get("type") == "downstream_called" for msg in captured
        )

    @pytest.mark.asyncio
    async def test_lifespan_scope_passes_through(self) -> None:
        """ASGI lifespan scope (type='lifespan') bypasses auth → downstream called."""
        from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

        called = []

        async def fake_send(message: dict[str, object]) -> None:
            called.append(message)

        async def fake_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            called.append("downstream")

        middleware = McpAuthMiddleware(fake_app)
        scope = {"type": "lifespan"}

        async def dummy_receive() -> dict[str, object]:
            return {"type": "lifespan.startup"}

        await middleware(scope, dummy_receive, fake_send)

        # Downstream called для lifespan (без auth check).
        assert "downstream" in called
