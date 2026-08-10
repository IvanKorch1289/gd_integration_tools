"""Pure ASGI tests для AIToolWhitelistMiddleware (cycle 46)."""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.ai_tool_whitelist import (
    AIToolWhitelistMiddleware,
)


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _downstream_ok(status_code: int = 200):
    """Downstream возвращающий OK (consumes body через receive)."""
    async def downstream(scope, receive, send):
        # Consume body (validates body re-injection).
        body_bytes = b""
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            body_bytes += msg.get("body", b"")
            more_body = msg.get("more_body", False)
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    method: str,
    path: str,
    state: dict | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        **({"state": state} if state is not None else {}),
    }


def _make_receive(body: bytes):
    """ASGI receive callable возвращающая body chunk."""
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


class TestAIToolWhitelistMiddlewarePureASGI:
    """Cycle 46: pure ASGI regression-тесты для AIToolWhitelistMiddleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без whitelist check."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = AIToolWhitelistMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/api/v1/agent/tools/invoke", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_passes_through_non_agent_path(self) -> None:
        """Path вне AGENT_PATH_PREFIX → пробрасывается без whitelist check."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AIToolWhitelistMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/users"),
            _make_receive(b'{"x":1}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_disabled_middleware_bypasses_all(self) -> None:
        """enabled=False → все запросы пробрасываются без check."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AIToolWhitelistMiddleware(app=app, enabled=False)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/agent/tools/invoke"),
            _make_receive(b'{"tool_name": "dangerous_tool"}'),
            send,
        )

        # 200 — даже invalid tool name проходит (disabled).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_whitelisted_tool_passes_through(self) -> None:
        """Tool в whitelist → пробрасывает downstream."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()

        def custom_check(tenant_id, tool_name) -> bool:
            return tool_name == "allowed_tool"

        mw = AIToolWhitelistMiddleware(app=app, on_tool_check=custom_check)

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/agent/tools/invoke",
                headers=[(b"x-tenant-id", b"tenant-a")],
            ),
            _make_receive(b'{"tool_name": "allowed_tool"}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_non_whitelisted_tool_returns_403(self) -> None:
        """Tool вне whitelist → 403 через send (no-raise, cycle 39)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream

        def custom_check(tenant_id, tool_name) -> bool:
            return tool_name == "allowed_tool"

        mw = AIToolWhitelistMiddleware(app=app, on_tool_check=custom_check)

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/agent/tools/invoke",
                headers=[(b"x-tenant-id", b"tenant-a")],
            ),
            _make_receive(b'{"tool_name": "dangerous_tool"}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "tool_not_whitelisted"
        assert parsed["tool"] == "dangerous_tool"

    @pytest.mark.asyncio
    async def test_missing_tool_name_returns_400(self) -> None:
        """Missing tool_name в body → 400."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AIToolWhitelistMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/agent/tools/invoke",
                headers=[(b"x-tenant-id", b"tenant-a")],
            ),
            _make_receive(b'{"other_field": 1}'),  # no tool_name
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 400
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "missing_tool_name"

    @pytest.mark.asyncio
    async def test_no_auth_no_tenant_header_returns_400(self) -> None:
        """Без auth context + без X-Tenant-ID header → 400 (S183: deny by default)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AIToolWhitelistMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/agent/tools/invoke"),
            _make_receive(b'{"tool_name": "any"}'),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 400
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["error"] == "missing_tenant"

    @pytest.mark.asyncio
    async def test_tenant_id_from_auth_context_takes_precedence(
        self,
    ) -> None:
        """tenant_id из auth context имеет приоритет над X-Tenant-ID header (S202)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()

        captured_tenant = {}

        def custom_check(tenant_id, tool_name) -> bool:
            captured_tenant["tenant_id"] = tenant_id
            return True

        mw = AIToolWhitelistMiddleware(app=app, on_tool_check=custom_check)

        # Mock auth context with tenant_id in metadata.
        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(metadata={"tenant_id": "auth-tenant"})

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/agent/tools/invoke",
                state={"auth": auth_ctx},
            ),
            _make_receive(b'{"tool_name": "any"}'),
            send,
        )

        # tenant_id из auth (не из header).
        assert captured_tenant["tenant_id"] == "auth-tenant"

    @pytest.mark.asyncio
    async def test_tenant_id_from_header_when_no_auth(self) -> None:
        """Без auth → tenant_id из X-Tenant-ID header."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()

        captured_tenant = {}

        def custom_check(tenant_id, tool_name) -> bool:
            captured_tenant["tenant_id"] = tenant_id
            return True

        mw = AIToolWhitelistMiddleware(app=app, on_tool_check=custom_check)

        send = AsyncMock()
        scope = _make_scope("POST", "/api/v1/agent/tools/invoke")
        scope["headers"] = [(b"x-tenant-id", b"header-tenant")]

        await mw(
            scope,
            _make_receive(b'{"tool_name": "any"}'),
            send,
        )

        assert captured_tenant["tenant_id"] == "header-tenant"

    @pytest.mark.asyncio
    async def test_malformed_body_passes_through(self) -> None:
        """Malformed body (invalid JSON) → пробрасывается downstream (defensive)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AIToolWhitelistMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/agent/tools/invoke"),
            _make_receive(b"not-json{{{"),
            send,
        )

        # 200 от downstream (malformed body не валится).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_downstream_consumes_replayed_body(self) -> None:
        """Cycle 46 invariant: downstream прочитывает body через replay_receive."""
        captured_body = {}

        async def downstream(scope, receive, send):
            body_bytes = b""
            more_body = True
            while more_body:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    break
                body_bytes += msg.get("body", b"")
                more_body = msg.get("more_body", False)
            captured_body["body"] = body_bytes
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = AIToolWhitelistMiddleware(app=app, enabled=False)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/agent/tools/invoke"),
            _make_receive(b"tool-payload"),
            send,
        )

        # Downstream прочитал body через replay (НЕ потерян).
        assert captured_body["body"] == b"tool-payload"

    @pytest.mark.asyncio
    async def test_per_tenant_isolation_in_whitelist_check(self) -> None:
        """Whitelist check получает корректный tenant_id для multi-tenant isolation."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        check_calls = []

        def custom_check(tenant_id, tool_name) -> bool:
            check_calls.append((tenant_id, tool_name))
            return True

        mw = AIToolWhitelistMiddleware(app=app, on_tool_check=custom_check)

        send = AsyncMock()
        scope = _make_scope(
            "POST",
            "/api/v1/agent/tools/invoke",
            state={"auth": type("Auth", (), {"metadata": {"tenant_id": "tenant-A"}})()},
        )
        await mw(
            scope,
            _make_receive(b'{"tool_name": "test_tool"}'),
            send,
        )

        # check был вызван с правильным tenant_id.
        assert check_calls == [("tenant-A", "test_tool")]

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_blocked(self) -> None:
        """Cycle 46 invariant: при 403 downstream НЕ вызывается."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = AIToolWhitelistMiddleware(
            app=app, on_tool_check=lambda t, n: False
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/agent/tools/invoke",
                headers=[(b"x-tenant-id", b"tenant-a")],
            ),
            _make_receive(b'{"tool_name": "blocked"}'),
            send,
        )

        # 403 отправлен.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
