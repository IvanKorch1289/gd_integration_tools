"""Sprint 1.1 (L5 Security Chain): regression-проверка проброса
principal/permissions из entrypoint-ов в ``DslService.dispatch`` через
``ExecutionContext``.

Покрывает матрицу «entrypoint × authorized principal / anonymous /
wrong role»:

* authorized principal (``"admin"`` с ``permissions=("role:admin",)``)
  на protected route (``pipeline.security=("role:admin",)``) →
  :func:`check_route_permission` вызывается с правильным principal и
  permissions → возвращает ``allowed=True`` → dispatch проходит;
* anonymous (``principal=""``) на protected route →
  ``check_route_permission`` видит ``"anonymous"`` → ``allowed=False``
  → :class:`RoutePermissionDeniedError` (403);
* wrong role (``"guest"`` с пустым permissions) на protected route →
  ``check_route_permission`` возвращает deny → 403;
* backward-compat: ``_dispatch_dsl`` без ``principal``/``permissions``
  ведёт себя как до Sprint 1.1 (``"anonymous"`` / ``()``,
  fail-closed для protected routes).

Запуск::

    .venv/bin/python -m pytest tests/unit/dsl/service/test_dispatch_authz_entrypoints.py -q
"""


from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import route_registry


class _NoopProcessor(BaseProcessor):
    """Минимальный процессор — для непустого pipeline."""

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


def _ok_exchange(body: Any = None) -> Exchange[Any]:
    """Создаёт ``Exchange`` со статусом COMPLETED."""
    exchange = Exchange(
        in_message=Message(body=body or {"x": 1}, headers={}),
    )
    exchange.out_message = Message(body=body or {"x": 1}, headers={})
    exchange.status = ExchangeStatus.completed
    return exchange


@pytest.fixture(autouse=True)
def _cleanup_registry() -> None:
    """Очистить ``route_registry`` после каждого теста."""
    yield
    route_registry.clear()


class TestHttpBridgeAuthContextPropagation:
    """``dispatch_action_or_dsl._dispatch_dsl`` пробрасывает
    principal/permissions в ``DslService.dispatch``.
    """

    @pytest.mark.asyncio
    async def test_authorized_principal_passes_through(self) -> None:
        """Authorized principal + matching permissions → check allow."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(True, "allowed")),
        ) as mock_check:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            bridge = await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
                principal="admin",
                permissions=("role:admin",),
            )

        assert bridge.success is True
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "admin"
        assert kwargs["permissions"] == ("role:admin",)
        assert kwargs["route_id"] == "r1"

    @pytest.mark.asyncio
    async def test_anonymous_fails_closed_for_protected_route(self) -> None:
        """Anonymous на protected route → check deny → BridgeResult(success=False).

        ``_dispatch_dsl`` оборачивает ``DslService.dispatch`` в
        ``BridgeResult``: ``RoutePermissionDeniedError`` ловится
        ``except Exception`` и конвертируется в failure-result. Это
        by design — Tier 3 fallback не должен пробрасывать exceptions
        в caller; вышестоящий HTTP/WS-layer решает что делать с
        BridgeResult.success=False (fault body / 5xx / close).
        Главное — fail-closed семантика: dispatch не выполняется при
        anonymous на protected route.
        """
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            bridge = await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
                principal="",
                permissions=(),
            )

        assert bridge.success is False
        assert bridge.via == "dsl"
        assert "missing_permissions:role:admin" in (bridge.error or "")
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"
        assert kwargs["permissions"] == ("role:admin",)

    @pytest.mark.asyncio
    async def test_wrong_role_fails_closed_for_protected_route(self) -> None:
        """Wrong role на protected route → check deny → BridgeResult(success=False)."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            bridge = await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
                principal="guest",
                permissions=("role:guest",),
            )

        assert bridge.success is False
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "guest"
        assert kwargs["permissions"] == ("role:admin",)

    @pytest.mark.asyncio
    async def test_backward_compat_no_principal(self) -> None:
        """Без ``principal``/``permissions`` → ``"anonymous"`` → fail-closed.

        Backward-compat: callers, которые не передают principal (как
        до Sprint 1.1), получают ту же семантику — fail-closed для
        protected routes.
        """
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            bridge = await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
            )

        assert bridge.success is False
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"

    @pytest.mark.asyncio
    async def test_public_route_skips_check(self) -> None:
        """Public route (security=None) → no check, dispatch passes."""
        pipeline = _make_pipeline("r1", security=None)
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(),
        ) as mock_check:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            bridge = await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
                principal="guest",
                permissions=(),
            )

        assert bridge.success is True
        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_execution_context_propagated_to_dispatch(self) -> None:
        """DslService.dispatch получает ExecutionContext с правильными полями."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(True, "allowed")),
        ), patch(
            "src.backend.dsl.service.facade.DslService.dispatch",
            new=AsyncMock(return_value=_ok_exchange()),
        ) as mock_dispatch:
            from src.backend.entrypoints._action_bridge import _dispatch_dsl

            await _dispatch_dsl(
                dsl_route_id="r1",
                payload={"k": "v"},
                headers=None,
                principal="alice",
                permissions=("role:admin", "scope:read"),
            )

        # mock_dispatch is on the class, so we look at the call args.
        call_kwargs = mock_dispatch.await_args.kwargs
        ctx = call_kwargs["context"]
        assert isinstance(ctx, ExecutionContext)
        assert ctx.principal == "alice"
        assert ctx.permissions == ("role:admin", "scope:read")


class TestSoapHandlerAuthContextPropagation:
    """SOAP-handler пробрасывает ``request.state.auth`` → ``DslService.dispatch``."""

    _SOAP_XML = (
        b'<soap:Envelope xmlns:soap="http://schemas.xmlsoap.org/soap/envelope/">'
        b"<soap:Body>"
        b"<adminOp xmlns='urn:example'/>"
        b"</soap:Body>"
        b"</soap:Envelope>"
    )

    @pytest.mark.asyncio
    async def test_soap_handler_propagates_auth_context(self) -> None:
        """``request.state.auth.principal`` → ``DslService.dispatch(context=...)``."""
        from fastapi import Request

        from src.backend.core.auth import AuthContext, AuthMethod
        from src.backend.entrypoints.soap import soap_handler

        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="admin-user",
            metadata={"permissions": ["role:admin"]},
        )
        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"SOAPAction": "adminOp"}
        mock_request.state.auth = auth
        mock_request.body = AsyncMock(return_value=self._SOAP_XML)

        captured_context: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured_context["principal"] = context.principal
            captured_context["permissions"] = context.permissions
            captured_context["route_id"] = context.route_id
            return _ok_exchange(body)

        with patch.object(
            soap_handler.action_handler_registry,
            "is_registered",
            return_value=False,
        ), patch(
            "src.backend.entrypoints.soap.soap_handler.get_dsl_service",
        ) as mock_get_dsl:
            mock_dsl = MagicMock()
            mock_dsl.dispatch = AsyncMock(side_effect=fake_dispatch)
            mock_get_dsl.return_value = mock_dsl

            with patch.object(
                soap_handler, "_build_soap_response", return_value="<ok/>",
            ):
                response = await soap_handler.handle_soap_request(mock_request)

        assert captured_context["principal"] == "admin-user"
        assert captured_context["permissions"] == ("role:admin",)
        assert captured_context["route_id"] == "soap.adminOp"
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_soap_handler_anonymous_fails_closed(self) -> None:
        """SOAP без ``request.state.auth`` → ``"anonymous"`` → fail-closed.

        ``check_route_permission`` получает ``"anonymous"`` principal,
        возвращает deny → ``DslService.dispatch`` рейзит
        ``RoutePermissionDeniedError`` → SOAP-handler ловит через
        ``BaseError`` branch → возвращает SOAP fault 500. Главное —
        что request без auth НЕ проходит на protected route.
        """
        from fastapi import Request

        from src.backend.entrypoints.soap import soap_handler

        mock_request = MagicMock(spec=Request)
        mock_request.headers = {"SOAPAction": "adminOp"}
        mock_request.state.auth = None
        mock_request.body = AsyncMock(return_value=self._SOAP_XML)

        pipeline = _make_pipeline("soap.adminOp", security=("role:admin",))
        route_registry.register(pipeline)

        with patch.object(
            soap_handler.action_handler_registry,
            "is_registered",
            return_value=False,
        ), patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check, patch.object(
            soap_handler, "_build_soap_fault", return_value="<fault/>",
        ):
            response = await soap_handler.handle_soap_request(mock_request)

        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"
        assert kwargs["route_id"] == "soap.adminOp"
        # SOAP-handler возвращает 500 при BaseError (RoutePermissionDeniedError
        # наследует BaseError → см. src/backend/core/errors.py). Главное —
        # НЕ 200 success.
        assert response.status_code != 200


class TestGraphQlDispatchAuthContextPropagation:
    """GraphQL ``_dispatch_dsl`` пробрасывает principal/permissions."""

    @pytest.mark.asyncio
    async def test_graphql_dispatch_propagates_principal(self) -> None:
        """``principal``/``permissions`` → ``DslService.dispatch(context=...)``."""
        from src.backend.entrypoints.graphql import schema as graphql_schema

        captured_context: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured_context["principal"] = context.principal
            captured_context["permissions"] = context.permissions
            return _ok_exchange(body)

        with patch(
            "src.backend.entrypoints.graphql.schema.get_dsl_service",
        ) as mock_get_dsl:
            mock_dsl = MagicMock()
            mock_dsl.dispatch = AsyncMock(side_effect=fake_dispatch)
            mock_get_dsl.return_value = mock_dsl

            result = await graphql_schema._dispatch_dsl(
                "r1",
                {"k": "v"},
                principal="alice",
                permissions=("role:admin", "scope:read"),
            )

        assert result.status == "completed"
        assert captured_context["principal"] == "alice"
        assert captured_context["permissions"] == ("role:admin", "scope:read")

    @pytest.mark.asyncio
    async def test_graphql_dispatch_anonymous_fails_closed(self) -> None:
        """GraphQL anonymous на protected route → 403."""
        from src.backend.entrypoints.graphql import schema as graphql_schema

        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            result = await graphql_schema._dispatch_dsl(
                "r1", {"k": "v"}, principal="", permissions=(),
            )

        assert result.status == "failed"
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"


class TestExecutionContextFromAuth:
    """``ExecutionContext.from_auth`` корректно собирает principal/permissions."""

    def test_from_auth_with_permissions_metadata(self) -> None:
        """``metadata.permissions`` (list) → кортеж в ExecutionContext.permissions."""
        from src.backend.core.auth import AuthContext, AuthMethod

        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata={"permissions": ["role:admin", "scope:read"]},
        )
        ctx = ExecutionContext.from_auth(auth)
        assert ctx.principal == "alice"
        assert ctx.permissions == ("role:admin", "scope:read")

    def test_from_auth_with_scope_metadata(self) -> None:
        """``metadata.scope`` (OAuth string) → tuple("scope:...") в permissions."""
        from src.backend.core.auth import AuthContext, AuthMethod

        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="bob",
            metadata={"scope": "credit.read credit.write"},
        )
        ctx = ExecutionContext.from_auth(auth)
        assert ctx.principal == "bob"
        assert ctx.permissions == ("scope:credit.read", "scope:credit.write")

    def test_from_auth_no_metadata(self) -> None:
        """Без permissions в metadata → пустой кортеж (fail-closed)."""
        from src.backend.core.auth import AuthContext, AuthMethod

        auth = AuthContext(method=AuthMethod.API_KEY, principal="carol")
        ctx = ExecutionContext.from_auth(auth)
        assert ctx.principal == "carol"
        assert ctx.permissions == ()

    def test_from_auth_none(self) -> None:
        """``auth=None`` → пустой principal + пустые permissions."""
        ctx = ExecutionContext.from_auth(None)
        assert ctx.principal == ""
        assert ctx.permissions == ()

    def test_from_auth_propagates_route_id(self) -> None:
        """``route_id`` пробрасывается в ExecutionContext.route_id."""
        from src.backend.core.auth import AuthContext, AuthMethod

        auth = AuthContext(method=AuthMethod.API_KEY, principal="alice")
        ctx = ExecutionContext.from_auth(auth, route_id="my-route")
        assert ctx.route_id == "my-route"


class TestExtractUserPermissionsHelper:
    """``extract_user_permissions`` — корректный разбор metadata."""

    def test_permissions_list(self) -> None:
        """Список permissions."""
        from src.backend.core.auth import AuthContext, AuthMethod
        from src.backend.core.auth.auth_context_helpers import extract_user_permissions

        auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata={"permissions": ["role:admin", "scope:read"]},
        )
        assert extract_user_permissions(auth) == ("role:admin", "scope:read")

    def test_scope_string_normalized(self) -> None:
        """OAuth scope-строка → ``scope:`` prefix."""
        from src.backend.core.auth import AuthContext, AuthMethod
        from src.backend.core.auth.auth_context_helpers import extract_user_permissions

        auth = AuthContext(
            method=AuthMethod.JWT,
            principal="bob",
            metadata={"scope": "a b c"},
        )
        assert extract_user_permissions(auth) == ("scope:a", "scope:b", "scope:c")

    def test_empty_metadata(self) -> None:
        """Пустой metadata → пустой кортеж."""
        from src.backend.core.auth import AuthContext, AuthMethod
        from src.backend.core.auth.auth_context_helpers import extract_user_permissions

        auth = AuthContext(method=AuthMethod.API_KEY, principal="alice")
        assert extract_user_permissions(auth) == ()

    def test_none_auth(self) -> None:
        """``auth=None`` → пустой кортеж."""
        from src.backend.core.auth.auth_context_helpers import extract_user_permissions

        assert extract_user_permissions(None) == ()
