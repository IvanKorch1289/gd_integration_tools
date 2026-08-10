"""Regression-тесты для api_key AuthContext write (cycle 34, B-13).

Проверяет, что после успешной валидации API-ключа в middleware
``scope['state']['auth']`` устанавливается ``AuthContext`` (interop
с audit_log и rpa_policy, которые читают ``auth.principal`` /
``auth.roles``).

B-13 fix (cycle 34): api_key пишет AuthContext в scope['state'] для
interop с audit_log/rpa_policy. До фикса audit_log получал ``anonymous``
для запросов через legacy APIKeyMiddleware path, что ломало actor_id
в ClickHouse audit_log.

Два сценария:
1. valid api_key → ``scope['state']['auth']`` заполнен ``AuthContext``
   с правильным ``method=API_KEY`` и ``principal="api_key_consumer"``;
2. invalid api_key → ``scope['state']['auth']`` отсутствует или ``None``
   (downstream не должен видеть ложный auth context).
"""


from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.auth import AuthContext, AuthMethod


def _start_message(send: AsyncMock):
    """Возвращает первое http.response.start сообщение из send-вызовов."""
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok():
    """Создаёт downstream, отвечающий 200 + empty body."""

    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    path: str = "/api/v1/protected",
    state: dict | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    """Создаёт минимальный ASGI HTTP scope для тестов."""
    return {
        "type": "http",
        "method": "GET",
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        **({"state": state} if state is not None else {}),
    }


def _make_receive():
    """Создаёт receive-callable возвращающий пустой body."""

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return receive


class TestAPIKeyAuthStateWriteCycle34:
    """B-13 fix: api_key пишет AuthContext в scope['state']."""

    @pytest.mark.asyncio
    async def test_valid_api_key_populates_state_auth(self) -> None:
        """Valid X-API-Key → ``scope['state']['auth']`` это ``AuthContext``."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()
        captured_scope: dict | None = None

        async def downstream(scope, receive, send):
            nonlocal captured_scope
            captured_scope = scope
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        with patch(
            "src.backend.entrypoints.middlewares.api_key.settings"
        ) as mock_settings:
            mock_settings.secure.api_key = "secret-key-123"
            mock_settings.secure.routes_without_api_key = []

            send = AsyncMock()
            await middleware(
                _make_scope(
                    headers=[(b"x-api-key", b"secret-key-123")],
                ),
                _make_receive(),
                send,
            )

        # Downstream был вызван с валидным api_key.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        assert captured_scope is not None

        # B-13 invariant: state.auth установлен и это AuthContext.
        state = captured_scope.get("state", {})
        auth = state.get("auth") if isinstance(state, dict) else None
        assert auth is not None, (
            "B-13 fix: valid api_key должен устанавливать scope['state']['auth']"
        )
        assert isinstance(auth, AuthContext)
        assert auth.method == AuthMethod.API_KEY
        assert auth.principal == "api_key_consumer"
        # Interop: audit_log читает auth.principal (строка) → работает.
        # Interop: rpa_policy читает getattr(auth, "roles", []) → вернёт
        # metadata["groups"] косвенно только если кто-то положит roles явно;
        # в нашем случае metadata содержит groups + tenant_id для downstream
        # extract_user_groups / extract_tenant_id.
        assert auth.metadata.get("tenant_id") == "default"
        assert "api_key_consumer" in tuple(auth.metadata.get("groups", ()))

    @pytest.mark.asyncio
    async def test_invalid_api_key_does_not_set_state_auth(self) -> None:
        """Invalid X-API-Key → ``scope['state']['auth']`` отсутствует или None."""
        from src.backend.entrypoints.middlewares.api_key import APIKeyMiddleware

        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван при 401")

        app.side_effect = downstream
        middleware = APIKeyMiddleware(app=app)
        middleware.compiled_patterns = []

        with patch(
            "src.backend.entrypoints.middlewares.api_key.settings"
        ) as mock_settings:
            mock_settings.secure.api_key = "correct-key"
            mock_settings.secure.routes_without_api_key = []

            send = AsyncMock()
            await middleware(
                _make_scope(
                    headers=[(b"x-api-key", b"wrong-key")],
                ),
                _make_receive(),
                send,
            )

        # 401 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 401
        # Downstream не вызывался — единственный способ проверить state.auth
        # это убедиться, что middleware не пытался установить его.
        # Дополнительная проверка: app не вызывался.
        app.assert_not_awaited()
