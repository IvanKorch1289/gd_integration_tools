"""Unit tests for IPRestrictionMiddleware (cycle 41 pure ASGI)."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.security.ip_restriction_store import get_ip_restriction_store
from src.backend.entrypoints.middlewares.admin_ip import IPRestrictionMiddleware


def _start_message(send: AsyncMock) -> dict | None:
    """Извлекает http.response.start."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


class TestIPRestrictionMiddleware:
    """Tests for :class:`IPRestrictionMiddleware` (cycle 41 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> IPRestrictionMiddleware:
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        mw = IPRestrictionMiddleware(app)
        store = get_ip_restriction_store()
        store.update_admin(set(), [])
        store.clear_route_rules()
        return mw

    def _scope(self, path: str, client_ip: str) -> dict:
        """ASGI scope для тестов."""
        return {
            "type": "http",
            "method": "GET",
            "url": f"http://test{path}",
            "path": path,
            "headers": [(b"host", b"test")],
            "client": (client_ip, 1234),
        }

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_non_admin_route_bypasses(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Non-admin routes are allowed for any IP."""
        send = AsyncMock()
        await middleware(self._scope("/public", "1.2.3.4"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_allowed_ip(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Admin route with allowed IP passes through."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        send = AsyncMock()
        await middleware(self._scope("/admin/users", "192.168.1.1"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_forbidden_ip(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Admin route with disallowed IP → 403 (no-raise pattern, cycle 41)."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        send = AsyncMock()
        await middleware(self._scope("/admin/users", "10.0.0.1"), AsyncMock(), send)

        # 403 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_admin_route_allowed_subnet(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Admin route with IP inside allowed subnet passes through."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.0.0/24"}, admin_routes=["/admin/*"])

        send = AsyncMock()
        await middleware(self._scope("/admin/users", "192.168.0.55"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_per_route_rule_takes_priority(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Per-route rule is checked before global admin rule."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/admin/special", ["192.168.1.1"])

        send = AsyncMock()
        await middleware(self._scope("/admin/special", "192.168.1.1"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_per_route_rule_forbids_admin_ip(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Per-route rule can forbid an IP that is allowed globally."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"10.0.0.1"}, admin_routes=["/admin/*"])
        store.set_route_rule("/admin/special", ["192.168.1.1"])

        send = AsyncMock()
        await middleware(self._scope("/admin/special", "10.0.0.1"), AsyncMock(), send)

        # 403 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403

    @pytest.mark.asyncio
    @pytest.mark.unit
    async def test_invalid_client_ip(self, middleware: IPRestrictionMiddleware) -> None:
        """Invalid client IP is treated as not allowed."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        send = AsyncMock()
        await middleware(self._scope("/admin/users", "not-an-ip"), AsyncMock(), send)

        # 403 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403


class TestIPRestrictionMiddlewarePureASGI:
    """Cycle 41: pure ASGI regression-тесты для IPRestrictionMiddleware."""

    @pytest.fixture
    def middleware(self) -> IPRestrictionMiddleware:
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        mw = IPRestrictionMiddleware(app)
        store = get_ip_restriction_store()
        store.update_admin(set(), [])
        store.clear_route_rules()
        return mw

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Non-HTTP scope (websocket) пробрасывается без IP-проверки."""
        # Используем собственный app+downstream (fixture использует отдельный app).
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = IPRestrictionMiddleware(app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        # websocket accept прошёл.
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_403_response_contains_json_detail(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """403 response body — JSON с detail полем (PII-safe)."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        send = AsyncMock()
        await middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/admin/users",
                "headers": [],
                "client": ("10.0.0.1", 0),
            },
            AsyncMock(),
            send,
        )

        # Body содержит JSON с detail.
        body_msg = next(
            c.args[0] for c in send.await_args_list
            if c.args[0]["type"] == "http.response.body"
        )
        import json
        body = json.loads(body_msg["body"].decode("utf-8"))
        assert "detail" in body
        # IP НЕ утекает в response body (PII-safe).
        assert "10.0.0.1" not in body_msg["body"].decode("utf-8")

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_blocked(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """При blocked path downstream НЕ вызывается (cycle 41 invariant)."""
        store = get_ip_restriction_store()
        store.update_admin(admin_ips={"192.168.1.1"}, admin_routes=["/admin/*"])

        # Создаём app с downstream который RAISE если вызван.
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = IPRestrictionMiddleware(app)

        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/admin/users",
                "headers": [],
                "client": ("10.0.0.1", 0),
            },
            AsyncMock(),
            send,
        )

        # 403 отправлен (если downstream был вызван, тест бы упал с AssertionError).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403

    @pytest.mark.asyncio
    async def test_no_client_info_denies_by_default(
        self, middleware: IPRestrictionMiddleware,
    ) -> None:
        """Cycle 41: если client IP отсутствует (anonymous) → 403.

        Cycle 41 invariant (security default): is_allowed возвращает
        False если client_ip is None. Без client info доступ
        запрещён по умолчанию.
        """
        # Очищаем store — пусть ТОЛЬКО клиент-без-IP check работает.
        store = get_ip_restriction_store()
        store.update_admin(set(), [])
        store.clear_route_rules()

        send = AsyncMock()
        await middleware(
            {
                "type": "http",
                "method": "GET",
                "path": "/admin/users",
                "headers": [],
                # Нет 'client' в scope.
            },
            AsyncMock(),
            send,
        )

        # 403 (security default — нет client IP → deny).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
