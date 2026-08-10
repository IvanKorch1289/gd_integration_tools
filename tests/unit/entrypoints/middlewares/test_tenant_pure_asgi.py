"""Pure ASGI regression-тесты для TenantMiddleware (cycle 38).

Middleware извлекает tenant_id из request и устанавливает в
``scope['state']`` + response header ``X-Tenant-ID``.

Приоритет (header > state > default) — критичен для multi-tenant
изоляции. В pure ASGI tenant_id резолвится ВНУТРИ send-wrapper
(после того, как inner auth middleware установил state['tenant_id'],
если применимо).
"""


from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_downstream(
    state_tenant: str | None = None, response_tenant: str | None = None,
):
    """Создаёт downstream app, возвращающий 200 + optional tenant.

    Опционально:
    - state_tenant: имитирует inner auth middleware, устанавливающий
      state['tenant_id'].
    - response_tenant: имитирует downstream, посылающий свой X-Tenant-ID
      (наш wrapper должен перезаписать).
    """

    async def downstream(scope, receive, send):
        if state_tenant is not None:
            scope.setdefault("state", {})["tenant_id"] = state_tenant
        response_headers = []
        if response_tenant is not None:
            response_headers.append((b"x-tenant-id", response_tenant.encode("latin-1")))
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": response_headers,
            },
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _start_headers(send_mock: AsyncMock) -> dict[bytes, bytes]:
    """Извлекает headers из http.response.start."""
    for call in send_mock.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return dict(msg.get("headers", []))
    return {}


@pytest.mark.asyncio
async def test_header_wins_over_state_when_both_set() -> None:
    """Header X-Tenant-ID имеет приоритет над state['tenant_id'] (если оба есть)."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    # Downstream пытается установить state, НО header должен выиграть.
    app.side_effect = _make_downstream(state_tenant="state-tenant")

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [(b"x-tenant-id", b"header-tenant")],
            },
            AsyncMock(),
            send,
        )

    headers = _start_headers(send)
    assert headers[b"x-tenant-id"] == b"header-tenant"


@pytest.mark.asyncio
async def test_state_used_when_no_header() -> None:
    """Если нет header — state['tenant_id'] (от auth middleware) используется."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    app.side_effect = _make_downstream(state_tenant="state-tenant")

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

    headers = _start_headers(send)
    assert headers[b"x-tenant-id"] == b"state-tenant"


@pytest.mark.asyncio
async def test_default_used_when_no_header_no_state() -> None:
    """Нет header + нет state → default tenant."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    app.side_effect = _make_downstream()  # no state

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        mw = TenantMiddleware(app, default_tenant="default-tenant")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

    headers = _start_headers(send)
    assert headers[b"x-tenant-id"] == b"default-tenant"


@pytest.mark.asyncio
async def test_overrides_downstream_x_tenant_id_header() -> None:
    """Если downstream послал X-Tenant-ID — мы перезаписываем (our source of truth)."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    # Downstream посылает свой X-Tenant-ID — мы должны перезаписать.
    app.side_effect = _make_downstream(
        state_tenant="correct-tenant", response_tenant="stale-downstream-value",
    )

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

    headers = _start_headers(send)
    # Наш resolved value (correct-tenant) — НЕ downstream value.
    assert headers[b"x-tenant-id"] == b"correct-tenant"


@pytest.mark.asyncio
async def test_passes_through_non_http_scope() -> None:
    """Non-HTTP scope (websocket) пробрасывается без модификации."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "websocket.accept"})

    app.side_effect = downstream
    mw = TenantMiddleware(app, default_tenant="default")
    send = AsyncMock()
    await mw(
        {"type": "websocket", "path": "/ws", "headers": []},
        AsyncMock(),
        send,
    )

    # websocket.accept прошёл без модификации.
    msg = send.await_args.args[0]
    assert msg["type"] == "websocket.accept"
    assert "headers" not in msg


@pytest.mark.asyncio
async def test_preserves_body_chunks_unchanged() -> None:
    """Body-сообщения пробрасываются без модификации."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"chunk-1"})
        await send({"type": "http.response.body", "body": b"chunk-2"})

    app.side_effect = downstream

    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=MagicMock(),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [(b"x-tenant-id", b"my-tenant")],
            },
            AsyncMock(),
            send,
        )

    body_msgs = [
        c.args[0] for c in send.await_args_list
        if c.args[0]["type"] == "http.response.body"
    ]
    assert len(body_msgs) == 2
    assert body_msgs[0]["body"] == b"chunk-1"
    assert body_msgs[1]["body"] == b"chunk-2"


@pytest.mark.asyncio
async def test_correlation_context_setter_called_with_resolved_tenant() -> None:
    """Cycle 38: set_correlation_context(tenant_id=X) вызывается с resolved value."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    app.side_effect = _make_downstream(state_tenant="auth-tenant")

    mock_setter = MagicMock()
    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        return_value=lambda **kwargs: mock_setter(**kwargs),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [],
            },
            AsyncMock(),
            send,
        )

    mock_setter.assert_called_once_with(tenant_id="auth-tenant")


@pytest.mark.asyncio
async def test_handles_missing_correlation_context_setter() -> None:
    """Если DI provider недоступен (test-env) — middleware НЕ падает."""
    from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

    app = AsyncMock()
    app.side_effect = _make_downstream()

    # Provider raises (unavailable) — middleware всё равно работает.
    with patch(
        "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
        side_effect=RuntimeError("DI provider unavailable"),
    ):
        mw = TenantMiddleware(app, default_tenant="default")
        send = AsyncMock()
        # Должен НЕ raise — fallback handled gracefully.
        await mw(
            {
                "type": "http",
                "method": "GET",
                "path": "/api",
                "headers": [(b"x-tenant-id", b"safe-tenant")],
            },
            AsyncMock(),
            send,
        )

    headers = _start_headers(send)
    # Header всё равно добавлен (X-Tenant-ID — наша primary responsibility).
    assert headers[b"x-tenant-id"] == b"safe-tenant"
