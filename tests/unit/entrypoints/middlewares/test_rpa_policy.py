"""Tests for RpaPolicyMiddleware (S171 M6 — security middleware, cycle 40 pure ASGI).

Deny-by-default policy для /api/v1/rpa/* endpoints:
- Block RCE-shaped operations unless explicit role granted
- Audit all RPA requests (success and deny)
- Optional IP allowlist (out of scope cycle 40)
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest


def _start_message(send: AsyncMock) -> dict | None:
    """Извлекает http.response.start."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    """Извлекает http.response.body."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


class TestRpaPolicyMiddleware:
    def test_processor_instantiates(self) -> None:
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware

        mw = RpaPolicyMiddleware(app=MagicMock())
        assert mw is not None

    @pytest.mark.asyncio
    async def test_blocks_rpa_path_without_role(self) -> None:
        """/api/v1/rpa/* без role 'rpa.admin' → 403."""
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware

        async def downstream(scope, receive, send):
            raise AssertionError("downstream должен быть skipped")

        app = AsyncMock()
        app.side_effect = downstream
        mw = RpaPolicyMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/rpa/shell/exec",
                "headers": [(b"x-roles", b"user")],
                "client": ("127.0.0.1", 0),
                "state": {},  # no auth context
            },
            AsyncMock(),
            send,
        )

        # 403 отправлен через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 403
        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert "detail" in parsed

    @pytest.mark.asyncio
    async def test_allows_rpa_path_with_role(self) -> None:
        """/api/v1/rpa/* WITH role 'rpa.admin' → pass through.

        Cycle 40: в pure ASGI auth middleware идёт OUTER (раньше) и
        устанавливает state['auth'] в scope ПЕРЕД тем, как rpa_policy
        __call__ отработает. Поэтому scope передаётся с уже
        установленным state['auth'].
        """
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = RpaPolicyMiddleware(app=app)

        send = AsyncMock()
        # Auth middleware (OUTER) уже установил state['auth'].
        auth = MagicMock(roles={"user", "rpa.admin"})
        await mw(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/v1/rpa/shell/exec",
                "headers": [],
                "client": ("127.0.0.1", 0),
                "state": {"auth": auth},
            },
            AsyncMock(),
            send,
        )

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_passes_through_non_rpa_path(self) -> None:
        """/api/v1/users/* → без проверки, pass through."""
        from src.backend.entrypoints.middlewares.rpa_policy import RpaPolicyMiddleware

        async def downstream(scope, receive, send):
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = RpaPolicyMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api/v1/users/list",
                "headers": [],
                "client": ("127.0.0.1", 0),
                "state": {},
            },
            AsyncMock(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
