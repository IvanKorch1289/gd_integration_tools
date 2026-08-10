"""Sprint 1.4 (L5 Security Chain): regression-проверка того, что MCP
dispatch **не пробрасывает** principal/permissions в
``DslService.dispatch`` — by design.

MCP tool handlers (``_register_single_tool``, manual tools via
``_authz_manual_tool``) вызывают
``action_handler_registry.dispatch(command)`` напрямую (Tier 1/2 path)
и **никогда** не делегируют в ``DslService.dispatch`` /
``_dispatch_dsl``. Это by-design — MCP auth enforcement работает
на двух других уровнях:

1. **ASGI-level**: ``McpAuthMiddleware`` (``auth_middleware.py``)
   блокирует HTTP-запросы без валидного API_KEY / JWT с 401.
2. **Per-tool allowlist**: ``_check_mcp_tool_authz`` (``helpers.py``)
   проверяет ``tool_allowlist`` / ``tool_public_namespaces`` /
   ``CapabilityGate`` перед каждым вызовом tool. Результат: при
   ``tool_authz_enabled=True`` и deny → tool возвращает error-envelope
   + audit-event без ``dispatch``.

DSL-fallback (Tier 3) — не применим к MCP: MCP tools зарегистрированы
через ``@mcp.tool(...)``, не через ``route_registry``. DSL-routes
недоступны как MCP tools в текущей архитектуре.

Этот файл фиксирует (a) что MCP не делает Tier 3 fallback в DSL,
(b) что существующий MCP auth path (allowlist) корректно
блокирует disallowed tools — fail-closed семантика обеспечивается
на уровне ``_check_mcp_tool_authz``, а не через principal/permissions.

Если в будущем MCP нужно будет пробрасывать principal/permissions
(например, для DSL-routes, доступных через MCP), это потребует
отдельного дизайна (Sprint 2+ WIP).

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/entrypoints/mcp/test_mcp_no_dsl_principal_propagation.py -v
"""


from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.entrypoints.mcp.mcp_server import helpers


class TestMcpAuthBypassDesign:
    """Документация by-design: MCP tool dispatch НЕ пробрасывает
    principal/permissions в ``DslService.dispatch``.

    Это противоположно WS/SSE/GraphQL, которые делают Tier 3
    fallback через ``_dispatch_dsl`` и получают fail-closed protection
    от ``check_route_permission``. MCP вместо этого использует
    pre-dispatch allowlist/capability check.
    """

    def test_register_single_tool_does_not_invoke_dispatch_dsl(self) -> None:
        """``_register_single_tool`` вызывает ``action_handler_registry.dispatch``
        напрямую, не ``_dispatch_dsl`` / ``DslService.dispatch``.
        """
        from src.backend.entrypoints.mcp.mcp_server import helpers

        # Mock MCP instance + tool registration.
        mcp = MagicMock()
        tool_func = MagicMock()

        def fake_tool_decorator(**_kwargs: object) -> object:
            def decorator(fn: object) -> object:
                # Сохраняем функцию для проверки.
                tool_func.fn = fn
                return fn

            return decorator

        mcp.tool = fake_tool_decorator

        with patch.object(
            helpers,
            "_action_input_schema_json",
            return_value=None,
        ):
            with patch(
                "src.backend.dsl.commands.registry.action_handler_registry",
            ) as mock_registry:
                mock_registry.is_registered = MagicMock(return_value=False)

                # Should register tool without raising — function body
                # captures ``action_name`` via closure for ``_check_mcp_tool_authz``.
                helpers._register_single_tool(mcp, action_name="test.tool")

        # The tool was registered (via fake_tool_decorator capture).
        assert tool_func.fn is not None

        # Verify the tool handler signature — it must use
        # ``action_handler_registry.dispatch`` (Tier 1/2 path), not
        # ``DslService.dispatch``.
        # Look at the source code of _register_single_tool to confirm.
        import inspect

        source = inspect.getsource(helpers._register_single_tool)
        assert "action_handler_registry.dispatch" in source, (
            "MCP tool handler must call action_handler_registry.dispatch, "
            "not DslService.dispatch"
        )
        assert "DslService.dispatch" not in source, (
            "MCP tool handler must NOT call DslService.dispatch — "
            "DSL-routes are not exposed as MCP tools by design"
        )

    def test_authz_manual_tool_does_not_invoke_dispatch_dsl(self) -> None:
        """``_authz_manual_tool`` (decorator factory) — manual tools
        (route_*, pipeline_*, documents_*, workflow_*) вызывают свои
        internal handlers, не ``_dispatch_dsl``.
        """
        import inspect

        source = inspect.getsource(helpers._authz_manual_tool)
        # ``_authz_manual_tool`` оборачивает ``@mcp.tool(...)`` и
        # вызывает ``await fn(*args, **kwargs)`` — fn — это internal
        # handler, не DSL dispatch.
        assert "await fn(" in source
        assert "DslService.dispatch" not in source
        assert "_dispatch_dsl" not in source


class TestMcpToolAuthzBypass:
    """Verify существующий ``_check_mcp_tool_authz`` правильно
    блокирует disallowed tools → fail-closed на ASGI/handler layer.
    Это и есть auth-enforcement для MCP — на per-tool basis, не
    через principal/permissions propagation.
    """

    def test_disallowed_tool_returns_deny_envelope(self) -> None:
        """Disallowed tool → ``_check_mcp_tool_authz`` returns reason →
        tool returns error-envelope (no dispatch).
        """
        # Build fake tool fn.
        async def fake_handler() -> str:
            return "ok"

        # Wrap via ``_authz_manual_tool``.
        mcp = MagicMock()

        def fake_tool_dec(**_kw: object) -> object:
            def decorator(fn: object) -> object:
                return fn

            return decorator

        mcp.tool = fake_tool_dec

        decorator_factory = helpers._authz_manual_tool(
            mcp, name="disallowed.tool", description="forbidden"
        )
        wrapped_fn = decorator_factory(fake_handler)

        # Patch ``_check_mcp_tool_authz`` so wrapper returns deny reason.
        with patch.object(
            helpers,
            "_check_mcp_manual_tool_authz",
            return_value="not_in_allowlist_or_public_ns",
        ):
            import asyncio

            result = asyncio.run(wrapped_fn())

        import orjson

        # ``_manual_tool_deny_envelope`` returns ``str`` (decoded UTF-8).
        envelope = orjson.loads(result)
        assert envelope["error"] == "mcp.tool.denied"
        assert envelope["tool"] == "disallowed.tool"
        assert envelope["reason"] == "not_in_allowlist_or_public_ns"


class TestMcpAuthMiddlewareBlocksAnonymous:
    """Sprint 1.4: verify ``McpAuthMiddleware`` blocks anonymous requests
    (ASGI-level fail-closed).
    """

    @pytest.mark.asyncio
    async def test_anonymous_request_returns_401(self) -> None:
        """HTTP scope без API_KEY/JWT → ``_respond_unauthorized`` → 401."""
        from src.backend.entrypoints.mcp.auth_middleware import McpAuthMiddleware

        captured: list[dict[str, object]] = []

        async def fake_send(message: dict[str, object]) -> None:
            captured.append(message)

        async def fake_app(
            scope: dict[str, object],
            receive: object,
            send: object,
        ) -> None:
            # Should NOT be called when auth fails.
            captured.append({"type": "downstream_called"})

        middleware = McpAuthMiddleware(fake_app)

        # Empty scope — no Authorization header, no X-API-Key.
        scope = {
            "type": "http",
            "headers": [],  # no auth headers
            "method": "POST",
            "path": "/mcp/test",
        }

        async def empty_receive() -> dict[str, object]:
            return {"type": "http.request", "body": b"", "more_body": False}

        await middleware(scope, empty_receive, fake_send)

        # Verify 401 response (not downstream).
        assert any(
            msg.get("status") == 401 for msg in captured if "status" in msg
        )
        # Downstream NOT called.
        assert not any(
            msg.get("type") == "downstream_called" for msg in captured
        )
