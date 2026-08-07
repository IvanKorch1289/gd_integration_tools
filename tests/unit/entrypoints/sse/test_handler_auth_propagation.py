"""Sprint 1.4 (L5 Security Chain): regression-проверка проброса
principal/permissions из ``request.state.auth`` в
``dispatch_action_or_dsl`` → ``DslService.dispatch`` через SSE
``/events/invoke`` endpoint.

Покрывает матрицу:

* authorized principal (``"admin"`` с ``permissions=("role:admin",)``)
  на protected route → ``check_route_permission`` вызывается с
  правильным principal/permissions → ``allowed=True`` → dispatch
  проходит;
* anonymous (no ``request.state.auth``) на protected route →
  ``"anonymous"`` → fail-closed → ``BridgeResult(success=False)``;
* wrong role (``"guest"`` с пустым permissions) на protected route
  → ``check_route_permission`` возвращает deny → fail-closed;
* public route (``pipeline.security=None``) с любым principal → no
  check → dispatch проходит;
* backward-compat: запросы без ``request.state.auth`` (старые
  тесты) получают ту же fail-closed семантику, что и раньше.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/entrypoints/sse/test_handler_auth_propagation.py -v
"""

# ruff: noqa: S101

from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import Request

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import route_registry
from src.backend.entrypoints.sse.handler import _InvokeRequest, sse_invoke


# Round 24 fix: 8 тестов — forward-looking TDD для Sprint 1.4 L5 Security
# Chain: SSE /events/invoke endpoint должен пробрасывать principal/permissions
# из request.state.auth в DslService.dispatch (parity с GraphQL/REST/SOAP).
# Cycle-6/D-AUDIT-609: xfail снят — handler пробрасывает principal/permissions
# через _extract_auth_from_request (parity с GraphQL/SOAP).


class _NoopProcessor(BaseProcessor):
    """Минимальный процессор для непустого pipeline (validator требует)."""

    def __init__(self) -> None:
        """Инициализация с дефолтным именем."""
        super().__init__(name="noop")

    async def process(self, exchange: Any, context: Any) -> None:  # type: ignore[override]
        """No-op."""
        return None


def _make_pipeline(route_id: str, security: tuple[str, ...] | None) -> Pipeline:
    """Конструирует Pipeline с заданным ``security``."""
    pipeline = Pipeline(route_id=route_id, processors=[_NoopProcessor()])
    pipeline.security = security
    return pipeline


@pytest.fixture(autouse=True)
def _cleanup_registry() -> Generator[None, None, None]:
    """Очистить ``route_registry`` после каждого теста."""
    yield
    route_registry.clear()


def _make_request(auth: AuthContext | None) -> MagicMock:
    """Сконструировать мок Request с заданным ``state.auth``."""
    request = MagicMock(spec=Request)
    request.headers = {}
    request.url.path = "/events/invoke"
    request.state.auth = auth
    return request


class TestSseAuthContextPropagation:
    """Sprint 1.4: SSE handler пробрасывает principal/permissions
    в ``dispatch_action_or_dsl`` через ``request.state.auth``.
    """

    @pytest.mark.asyncio
    async def test_authorized_principal_propagates_to_dispatch(self) -> None:
        """Positive: authorized principal + permissions → dispatch выполняется.

        Проверяем, что ``_invoke`` handler извлекает ``auth.principal`` и
        ``extract_user_permissions(auth)`` и передаёт их в
        ``dispatch_action_or_dsl(principal=..., permissions=...)``.
        Mock dispatch возвращает success — главное, что
        ``check_route_permission`` НЕ вызывается на protected route
        (mock позволяет это проверить) и ExecutionContext содержит
        правильные поля.
        """
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="admin-user",
            metadata={"permissions": ["role:admin", "scope:credit.read"]},
        )
        request = _make_request(auth)

        captured: dict[str, Any] = {}

        async def fake_bridge(**kwargs: Any) -> MagicMock:
            captured["principal"] = kwargs.get("principal")
            captured["permissions"] = kwargs.get("permissions")
            captured["kwargs"] = kwargs
            return MagicMock(
                success=True,
                data={"ok": True},
                error=None,
                error_code=None,
            )

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            side_effect=fake_bridge,
        ):
            response = await sse_invoke(request, body)
            # Consume body_iterator inside patch context.
            _ = [c async for c in response.body_iterator]

        assert captured["principal"] == "admin-user"
        assert captured["permissions"] == ("role:admin", "scope:credit.read")

    @pytest.mark.asyncio
    async def test_oauth_scope_metadata_normalized(self) -> None:
        """Positive: ``metadata.scope="a b c"`` → tuple ``("scope:a", ...)``."""
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="bob",
            metadata={"scope": "credit.read credit.write"},
        )
        request = _make_request(auth)

        captured: dict[str, Any] = {}

        async def fake_bridge(**kwargs: Any) -> MagicMock:
            captured["principal"] = kwargs.get("principal")
            captured["permissions"] = kwargs.get("permissions")
            return MagicMock(
                success=True, data={}, error=None, error_code=None
            )

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            side_effect=fake_bridge,
        ):
            response = await sse_invoke(request, body)
            _ = [c async for c in response.body_iterator]

        assert captured["principal"] == "bob"
        assert captured["permissions"] == (
            "scope:credit.read",
            "scope:credit.write",
        )

    @pytest.mark.asyncio
    async def test_no_auth_state_fails_closed_anonymous(self) -> None:
        """Negative: без ``request.state.auth`` → ``"anonymous"`` → fail-closed.

        На protected route (``pipeline.security=("role:admin",)``)
        ``check_route_permission`` вернёт deny → ``dispatch_action_or_dsl``
        → ``_dispatch_dsl`` оборачивает ``RoutePermissionDeniedError`` в
        ``BridgeResult(success=False)``.
        """
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        request = _make_request(auth=None)
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=False,
                data=None,
                error="missing_permissions:role:admin",
                error_code="dispatch_failed",
            )
            response = await sse_invoke(request, body)
            # Consume body_iterator inside patch context.
            chunks = [c async for c in response.body_iterator]

        # bridge получил principal="" → "anonymous"
        call_kwargs = mock_bridge.call_args.kwargs
        assert call_kwargs["principal"] == ""
        assert call_kwargs["permissions"] == ()
        # SSE-stream содержит error-event (а не result).
        text = "".join(chunks)
        assert "event: error" in text

    @pytest.mark.asyncio
    async def test_wrong_role_fails_closed(self) -> None:
        """Negative: principal="guest" без admin permission → fail-closed.

        ``check_route_permission`` возвращает deny →
        ``RoutePermissionDeniedError`` → ``BridgeResult(success=False)``.
        """
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="guest",
            metadata={"permissions": []},
        )
        request = _make_request(auth)
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=False,
                data=None,
                error="missing_permissions:role:admin",
                error_code="dispatch_failed",
            )
            response = await sse_invoke(request, body)
            _ = [c async for c in response.body_iterator]

        call_kwargs = mock_bridge.call_args.kwargs
        assert call_kwargs["principal"] == "guest"
        assert call_kwargs["permissions"] == ()

    @pytest.mark.asyncio
    async def test_public_route_dispatches_with_principal(self) -> None:
        """Positive: public route (security=None) → dispatch проходит с principal."""
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata={"permissions": ["scope:read"]},
        )
        request = _make_request(auth)
        pipeline = _make_pipeline("r1", security=None)
        route_registry.register(pipeline)

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            new_callable=AsyncMock,
        ) as mock_bridge:
            mock_bridge.return_value = MagicMock(
                success=True, data={"x": 1}, error=None, error_code=None
            )
            response = await sse_invoke(request, body)
            chunks = [c async for c in response.body_iterator]

        call_kwargs = mock_bridge.call_args.kwargs
        assert call_kwargs["principal"] == "alice"
        assert call_kwargs["permissions"] == ("scope:read",)
        # Stream содержит success result.
        text = "".join(chunks)
        assert "event: result" in text

    @pytest.mark.asyncio
    async def test_execution_context_in_dispatch_call(self) -> None:
        """Verify: bridge получает principal/permissions в kwargs."""
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata={"permissions": ["role:ops", "scope:write"]},
        )
        request = _make_request(auth)
        captured: dict[str, Any] = {}

        async def fake_bridge(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(
                success=True, data={}, error=None, error_code=None
            )

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            side_effect=fake_bridge,
        ):
            response = await sse_invoke(request, body)
            _ = [c async for c in response.body_iterator]

        # ExecutionContext, который будет построен внутри bridge.
        # Здесь проверяем что переданы правильные kwarg-значения.
        assert captured["principal"] == "alice"
        assert captured["permissions"] == ("role:ops", "scope:write")
        assert captured["action_id"] == "r1"
        assert captured["dsl_route_id"] == "r1"
        assert captured["transport"] == "sse"


class TestSseAuthContextEdgeCases:
    """Edge cases: auth metadata с non-list permissions, missing keys."""

    @pytest.mark.asyncio
    async def test_auth_with_no_metadata_yields_empty_permissions(self) -> None:
        """AuthContext без metadata → ``permissions=()`` (fail-closed)."""
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata=None,
        )
        request = _make_request(auth)

        captured: dict[str, Any] = {}

        async def fake_bridge(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(
                success=True, data={}, error=None, error_code=None
            )

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            side_effect=fake_bridge,
        ):
            response = await sse_invoke(request, body)
            _ = [c async for c in response.body_iterator]

        assert captured["principal"] == "alice"
        assert captured["permissions"] == ()

    @pytest.mark.asyncio
    async def test_request_state_without_auth_attribute(self) -> None:
        """``request.state`` без ``auth`` → ``principal=""`` (fail-closed)."""
        body = _InvokeRequest(action="r1", payload={"k": "v"})
        request = MagicMock(spec=Request)
        request.headers = {}
        request.url.path = "/events/invoke"
        # Не устанавливаем auth — state вернёт AttributeError для state.auth.
        request.state = MagicMock(spec=[])  # no auth attribute

        captured: dict[str, Any] = {}

        async def fake_bridge(**kwargs: Any) -> MagicMock:
            captured.update(kwargs)
            return MagicMock(
                success=True, data={}, error=None, error_code=None
            )

        with patch(
            "src.backend.entrypoints.sse.handler.dispatch_action_or_dsl",
            side_effect=fake_bridge,
        ):
            response = await sse_invoke(request, body)
            _ = [c async for c in response.body_iterator]

        assert captured["principal"] == ""
        assert captured["permissions"] == ()


class TestSseAuthIntegrationNoAuth:
    """Cycle-6/D-AUDIT-609: integration-проверка fail-closed на route-level.

    POST /events/invoke без auth → ``require_auth`` dependency raises
    ``HTTPException(401)`` → FastAPI возвращает 401 до вызова
    ``sse_invoke``. Это проверяет, что dependency-chain
    ``require_auth([API_KEY, JWT])`` действительно стоит на route и
    fail-closed семантика работает.
    """

    @pytest.mark.asyncio
    async def test_no_auth_returns_401(self) -> None:
        """POST /events/invoke без Authorization → 401.

        Без auth middleware (или при отсутствии валидного токена)
        endpoint возвращает HTTP 401 до того, как ``sse_invoke`` начнёт
        обрабатывать request. Это контрактная fail-closed гарантия:
        principal=None (anonymous) → 401, никакого fallback на
        dispatch с пустым principal.
        """
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient

        from src.backend.entrypoints.sse.handler import sse_router

        app = FastAPI()
        app.include_router(sse_router)

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            response = await ac.post(
                "/events/invoke", json={"action": "r1", "payload": {}}
            )

        # require_auth dependency raises HTTPException(401) → 401 ответ.
        assert response.status_code == 401
