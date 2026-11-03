"""ADR-0427 — проброс principal/permissions на WS- и GraphQL-поверхности.

Контекст дефекта
----------------
ADR-0421 закрыл проверку прав на action-поверхностях: action с
``permissions`` или с ``admin``-префиксом требует соответствующего права.
REST-поверхность (``POST /api/v1/invocations``) передаёт ``principal`` и
``permissions`` в ``InvocationRequest`` → проверка работает.

WS (``/ws/invocations``) и GraphQL (``/graphql``) эти данные **не передавали**:
* WS — ``InvocationRequest`` собирался без principal/permissions;
* GraphQL — auto-schema-резолвер вызывал ``dispatch_action`` без них, а
  аннотация ``info: "Info | None"`` не распознавалась Strawberry как
  reserved-параметр → ``info`` попадал в GraphQL-схему как обычный аргумент,
  а auth-контекст не доходил до резолвера.

Итог: admin-action отклонялся даже для легитимного админа (fail-closed и
одновременно over-restrictive).

Проверяется здесь:
* WS: principal/permissions сессии попадают в ``InvocationRequest``;
* GraphQL: резолвер auto-schema передаёт principal/permissions в
  ``dispatch_action`` и ``info`` не является GraphQL-аргументом.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.commands.action_registry import ADMIN_PERMISSION

pytestmark = pytest.mark.unit


class _FakeAuthContext:
    """Минимальный AuthContext: principal + admin-роль."""

    def __init__(self, principal: str, *, admin: bool = False) -> None:
        self.principal = principal
        self.metadata: dict[str, Any] = {}
        if admin:
            self.metadata["admin_roles"] = ["super_admin"]


@pytest.mark.asyncio
async def test_graphql_resolver_propagates_auth_to_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GraphQL auto-schema: principal/permissions доходят до ``dispatch_action``."""
    from src.backend.entrypoints.graphql import auto_schema

    captured: dict[str, Any] = {}

    async def _fake_dispatch_action(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "src.backend.entrypoints.base.dispatch_action", _fake_dispatch_action
    )

    resolver = auto_schema._build_resolver("admin.get_config")
    info = SimpleNamespace(context={"auth": _FakeAuthContext("alice", admin=True)})

    result = await resolver(info, {"x": 1})

    assert captured["principal"] == "alice"
    assert ADMIN_PERMISSION in captured["permissions"]
    assert result["success"] is True


@pytest.mark.asyncio
async def test_graphql_resolver_without_auth_is_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Без auth-контекста principal/permissions пустые (fail-closed)."""
    from src.backend.entrypoints.graphql import auto_schema

    captured: dict[str, Any] = {}

    async def _fake_dispatch_action(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return {"ok": True}

    monkeypatch.setattr(
        "src.backend.entrypoints.base.dispatch_action", _fake_dispatch_action
    )

    resolver = auto_schema._build_resolver("orders.get")
    await resolver(SimpleNamespace(context={"auth": None}), {})

    assert captured["principal"] == ""
    assert tuple(captured["permissions"]) == ()


def test_graphql_info_is_not_a_graphql_argument() -> None:
    """``info`` — reserved-параметр Strawberry, а не аргумент GraphQL-схемы."""
    from src.backend.entrypoints.graphql import auto_schema

    resolver = auto_schema._build_resolver("orders.get")
    annotations = resolver.__annotations__
    assert "info" in annotations
    assert annotations["info"] is not None


@pytest.mark.asyncio
async def test_ws_invocation_carries_session_principal_and_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS: principal/permissions аутентифицированной сессии → InvocationRequest."""
    from src.backend.entrypoints.websocket import ws_invocations as ws_mod
    from src.backend.entrypoints.websocket.ws_invocations import websocket_invocations

    captured: dict[str, Any] = {}

    class _Channel:
        async def register(self, invocation_id: str, conn: Any) -> None:
            del invocation_id, conn

    class _Registry:
        def get(self, name: str) -> Any:
            return _Channel() if name == "ws" else None

    class _State:
        def __init__(self) -> None:
            self.reply_registry = _Registry()
            self.invoker = MagicMock()

    class _App:
        def __init__(self) -> None:
            self.state = _State()

    class _WS:
        def __init__(self) -> None:
            self.app = _App()
            self.state = SimpleNamespace(
                ws_session=SimpleNamespace(principal="bob", is_admin=True)
            )
            self.headers: dict[str, str] = {}
            self.cookies: dict[str, str] = {}
            self.query_params: dict[str, str] = {}
            self.sent: list[dict[str, Any]] = []
            self._done = False

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> Any:
            if self._done:
                from fastapi import WebSocketDisconnect

                raise WebSocketDisconnect()
            self._done = True
            return {"type": "invoke", "action": "admin.get_config", "mode": "sync"}

        async def send_json(self, data: dict[str, Any]) -> None:
            self.sent.append(data)

        async def close(self, code: int = 1000, reason: str | None = None) -> None:
            del code, reason

    invoker = MagicMock()

    async def _capture(request: Any) -> Any:
        captured["request"] = request
        return SimpleNamespace(status="completed", invocation_id="x")

    invoker.invoke = AsyncMock(side_effect=_capture)
    ws = _WS()
    ws.app.state.invoker = invoker

    monkeypatch.setattr(ws_mod, "_authenticate_handshake", AsyncMock(return_value=True))

    await websocket_invocations(ws)  # type: ignore[arg-type]

    request = captured.get("request")
    assert request is not None, "InvocationRequest не создан"
    assert request.principal == "bob"
    assert ADMIN_PERMISSION in request.permissions
