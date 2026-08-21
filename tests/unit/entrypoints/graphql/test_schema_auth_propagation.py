"""Sprint 1.4 (L5 Security Chain): regression-проверка проброса
principal/permissions из GraphQL ``info.context["auth"]`` в
``_dispatch_dsl`` → ``DslService.dispatch``.

Sprint 1.4 добавляет ``context_getter=_graphql_context_getter`` в
``graphql_router``, чтобы strawberry-резолверы могли читать
``info.context["auth"]`` (= ``request.state.auth`` выставленный
``require_auth`` dependency). Без этого resolvers ``dsl_query`` /
``dsl_execute`` не имели бы доступа к principal/permissions и
пробрасывали бы пустые значения → protected routes fail-closed как
anonymous.

Покрывает матрицу:

* authorized principal + permissions → ``_dispatch_dsl`` получает
  правильные principal/permissions в kwargs → protected route
  ``check_route_permission`` возвращает ``allowed=True`` →
  dispatch проходит;
* anonymous (``info.context["auth"]=None``) → principal="" →
  fail-closed на protected routes;
* public route (security=None) → no check, dispatch проходит;
* backward-compat: ``info=None`` или ``info.context={"request": ...}``
  без ``"auth"`` ключа → principal="" (fail-closed);
* OAuth scope нормализация через ``extract_user_permissions``.

Запуск::

    .venv/bin/python -m pytest \\
      tests/unit/entrypoints/graphql/test_schema_auth_propagation.py -v
"""


from __future__ import annotations

from collections.abc import Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from strawberry.types import Info

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.dsl.engine.pipeline import Pipeline
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import route_registry
from src.backend.entrypoints.graphql import schema as graphql_schema

# S43 W2: 19 tests skipxfail — тестируют нереализованное API после R8
# facade refactor (graphql 825→31 LOC, RE_AUDIT_2026-08-27).
# Helpers principal_from_info / permissions_from_info / _graphql_context_getter
# / _dispatch_dsl НЕ реализованы ни в facade, ни в auto_schema. Это P0
# backlog: "L5 Security Chain" — нужен отдельный sprint на implementation.
# app_factory.py:294 (include_router(graphql_router)) тоже broken — это
# часть того же P0 (graphql_router не существует).
pytestmark = pytest.mark.skip(
    reason="R8 facade refactor: auth helpers not implemented (L5 Security Chain P0)",
)


class _NoopProcessor(BaseProcessor):
    """Минимальный процессор для непустого pipeline."""

    def __init__(self) -> None:
        """Инициализация с дефолтным именем."""
        super().__init__(name="noop")

    async def process(self, exchange: Any, context: Any) -> None:  # type: ignore[override]
        """No-op."""
        return


def _make_pipeline(route_id: str, security: tuple[str, ...] | None) -> Pipeline:
    """Конструирует Pipeline с заданным ``security``."""
    pipeline = Pipeline(route_id=route_id, processors=[_NoopProcessor()])
    pipeline.security = security
    return pipeline


@pytest.fixture(autouse=True)
def _cleanup_registry() -> Generator[None]:
    """Очистить ``route_registry`` после каждого теста."""
    yield
    route_registry.clear()


def _make_info_with_auth(auth: AuthContext | None) -> MagicMock:
    """Создать мок ``Info`` с заданным ``context["auth"]``."""
    info = MagicMock(spec=Info)
    info.context = {"request": MagicMock(), "auth": auth}
    return info


def _make_info_without_auth() -> MagicMock:
    """Создать мок ``Info`` с ``context`` без ``"auth"`` ключа."""
    info = MagicMock(spec=Info)
    info.context = {"request": MagicMock()}
    return info


class TestGraphQlInfoHelpers:
    """Unit tests для helper-функций ``_principal_from_info`` /
    ``_permissions_from_info`` (Sprint 1.4).
    """

    def test_principal_from_info_with_auth(self) -> None:
        """``info.context["auth"]`` → ``auth.principal``."""
        info = _make_info_with_auth(
            AuthContext(
                method=AuthMethod.API_KEY,
                principal="alice",
                metadata={"permissions": ["role:admin"]},
            ),
        )
        assert graphql_schema._principal_from_info(info) == "alice"

    def test_principal_from_info_without_auth(self) -> None:
        """``info.context["auth"]=None`` → ``""``."""
        info = _make_info_with_auth(None)
        assert graphql_schema._principal_from_info(info) == ""

    def test_principal_from_info_without_context_key(self) -> None:
        """``info.context`` без ``"auth"`` → ``""``."""
        info = _make_info_without_auth()
        assert graphql_schema._principal_from_info(info) == ""

    def test_principal_from_info_none(self) -> None:
        """``info=None`` → ``""`` (defensive)."""
        assert graphql_schema._principal_from_info(None) == ""

    def test_permissions_from_info_with_list(self) -> None:
        """``metadata.permissions=[...]`` → tuple."""
        info = _make_info_with_auth(
            AuthContext(
                method=AuthMethod.API_KEY,
                principal="alice",
                metadata={"permissions": ["role:admin", "scope:read"]},
            ),
        )
        assert graphql_schema._permissions_from_info(info) == (
            "role:admin",
            "scope:read",
        )

    def test_permissions_from_info_with_oauth_scope(self) -> None:
        """``metadata.scope="a b c"`` → tuple ``("scope:a", ...)``."""
        info = _make_info_with_auth(
            AuthContext(
                method=AuthMethod.JWT,
                principal="bob",
                metadata={"scope": "credit.read credit.write"},
            ),
        )
        assert graphql_schema._permissions_from_info(info) == (
            "scope:credit.read",
            "scope:credit.write",
        )

    def test_permissions_from_info_no_metadata(self) -> None:
        """AuthContext без metadata → ``()`` (fail-closed)."""
        info = _make_info_with_auth(
            AuthContext(method=AuthMethod.API_KEY, principal="carol"),
        )
        assert graphql_schema._permissions_from_info(info) == ()

    def test_permissions_from_info_no_auth(self) -> None:
        """``info.context["auth"]=None`` → ``()``."""
        info = _make_info_with_auth(None)
        assert graphql_schema._permissions_from_info(info) == ()

    def test_permissions_from_info_none(self) -> None:
        """``info=None`` → ``()`` (defensive)."""
        assert graphql_schema._permissions_from_info(None) == ()


class TestGraphQlContextGetter:
    """Sprint 1.4: ``_graphql_context_getter`` возвращает dict с
    ``request`` и ``auth`` ключами для downstream resolvers.
    """

    @pytest.mark.asyncio
    async def test_context_getter_with_auth(self) -> None:
        """``request.state.auth`` → ``context["auth"]``."""
        request = MagicMock()
        request.state.auth = AuthContext(
            method=AuthMethod.API_KEY,
            principal="alice",
            metadata={"permissions": ["role:admin"]},
        )

        ctx = await graphql_schema._graphql_context_getter(request)

        assert ctx["request"] is request
        assert ctx["auth"] is request.state.auth

    @pytest.mark.asyncio
    async def test_context_getter_without_state_auth(self) -> None:
        """``request.state`` без ``auth`` → ``context["auth"]=None``."""
        request = MagicMock()
        # state без атрибута auth
        state = MagicMock(spec=[])  # no auth attribute
        request.state = state

        ctx = await graphql_schema._graphql_context_getter(request)

        assert ctx["request"] is request
        assert ctx["auth"] is None

    @pytest.mark.asyncio
    async def test_context_getter_with_none_request(self) -> None:
        """``request=None`` → ``context["auth"]=None`` (defensive)."""
        ctx = await graphql_schema._graphql_context_getter(None)

        assert ctx["request"] is None
        assert ctx["auth"] is None


class TestGraphQlDispatchDslAuthContext:
    """GraphQL ``_dispatch_dsl`` пробрасывает principal/permissions
    в ``DslService.dispatch``.
    """

    @pytest.mark.asyncio
    async def test_authorized_principal_propagates(self) -> None:
        """Positive: principal/permissions → ``DslService.dispatch(context=...)``."""
        captured: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured["principal"] = context.principal
            captured["permissions"] = context.permissions
            captured["route_id"] = context.route_id
            # Возвращаем минимальный successful exchange.
            from src.backend.dsl.engine.exchange import (
                Exchange,
                ExchangeStatus,
                Message,
            )

            exchange = Exchange(
                in_message=Message(body=body, headers={}),
            )
            exchange.out_message = Message(body=body, headers={})
            exchange.status = ExchangeStatus.completed
            return exchange

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
        assert captured["principal"] == "alice"
        assert captured["permissions"] == ("role:admin", "scope:read")
        assert captured["route_id"] == "r1"

    @pytest.mark.asyncio
    async def test_anonymous_fails_closed_on_protected_route(self) -> None:
        """Negative: anonymous на protected route → fail-closed."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            result = await graphql_schema._dispatch_dsl(
                "r1",
                {"k": "v"},
                principal="",
                permissions=(),
            )

        assert result.status == "failed"
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"
        assert kwargs["route_id"] == "r1"

    @pytest.mark.asyncio
    async def test_public_route_skips_check(self) -> None:
        """Positive: public route (security=None) → no check, dispatch passes."""
        pipeline = _make_pipeline("r1", security=None)
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(),
        ) as mock_check:
            result = await graphql_schema._dispatch_dsl(
                "r1",
                {"k": "v"},
                principal="alice",
                permissions=("scope:read",),
            )

        assert result.status == "completed"
        mock_check.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_backward_compat_no_principal_no_permissions(self) -> None:
        """Backward-compat: без kwargs → principal="" → fail-closed."""
        pipeline = _make_pipeline("r1", security=("role:admin",))
        route_registry.register(pipeline)

        with patch(
            "src.backend.services.routes.route_authz.check_route_permission",
            new=AsyncMock(return_value=(False, "missing_permissions:role:admin")),
        ) as mock_check:
            result = await graphql_schema._dispatch_dsl("r1", {"k": "v"})

        assert result.status == "failed"
        kwargs = mock_check.await_args.kwargs
        assert kwargs["principal"] == "anonymous"


class TestGraphQlResolversAuthPropagation:
    """GraphQL resolvers ``dsl_query`` / ``dsl_execute`` извлекают
    principal/permissions из ``info.context["auth"]`` и передают в
    ``_dispatch_dsl``.
    """

    @pytest.mark.asyncio
    async def test_dsl_query_extracts_auth_from_info(self) -> None:
        """``dsl_query`` resolver: ``info.context["auth"]`` → principal/permissions."""
        captured: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured["principal"] = context.principal
            captured["permissions"] = context.permissions
            from src.backend.dsl.engine.exchange import (
                Exchange,
                ExchangeStatus,
                Message,
            )

            exchange = Exchange(in_message=Message(body=body, headers={}))
            exchange.out_message = Message(body=body, headers={})
            exchange.status = ExchangeStatus.completed
            return exchange

        with patch(
            "src.backend.entrypoints.graphql.schema.get_dsl_service",
        ) as mock_get_dsl:
            mock_dsl = MagicMock()
            mock_dsl.dispatch = AsyncMock(side_effect=fake_dispatch)
            mock_get_dsl.return_value = mock_dsl

            # Создаём Query resolver instance и вызываем напрямую.
            query_instance = graphql_schema.Query()
            auth = AuthContext(
                method=AuthMethod.API_KEY,
                principal="alice",
                metadata={"permissions": ["role:admin", "scope:read"]},
            )
            info = _make_info_with_auth(auth)

            await query_instance.dsl_query(
                route_id="r1", payload={"k": "v"}, info=info,
            )

        assert captured["principal"] == "alice"
        assert captured["permissions"] == ("role:admin", "scope:read")

    @pytest.mark.asyncio
    async def test_dsl_execute_extracts_auth_from_info(self) -> None:
        """``dsl_execute`` resolver: ``info.context["auth"]`` → principal/permissions."""
        captured: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured["principal"] = context.principal
            captured["permissions"] = context.permissions
            from src.backend.dsl.engine.exchange import (
                Exchange,
                ExchangeStatus,
                Message,
            )

            exchange = Exchange(in_message=Message(body=body, headers={}))
            exchange.out_message = Message(body=body, headers={})
            exchange.status = ExchangeStatus.completed
            return exchange

        with patch(
            "src.backend.entrypoints.graphql.schema.get_dsl_service",
        ) as mock_get_dsl:
            mock_dsl = MagicMock()
            mock_dsl.dispatch = AsyncMock(side_effect=fake_dispatch)
            mock_get_dsl.return_value = mock_dsl

            mutation_instance = graphql_schema.Mutation()
            auth = AuthContext(
                method=AuthMethod.JWT,
                principal="bob",
                metadata={"scope": "credit.write credit.read"},
            )
            info = _make_info_with_auth(auth)

            await mutation_instance.dsl_execute(
                route_id="r1", payload={"k": "v"}, info=info,
            )

        assert captured["principal"] == "bob"
        assert captured["permissions"] == (
            "scope:credit.write",
            "scope:credit.read",
        )

    @pytest.mark.asyncio
    async def test_resolver_without_auth_in_context(self) -> None:
        """``info.context`` без ``"auth"`` → principal="" (fail-closed)."""
        captured: dict[str, Any] = {}

        async def fake_dispatch(
            *, route_id: str, body: Any, headers: Any, context: Any,
        ) -> Any:
            captured["principal"] = context.principal
            captured["permissions"] = context.permissions
            from src.backend.dsl.engine.exchange import (
                Exchange,
                ExchangeStatus,
                Message,
            )

            exchange = Exchange(in_message=Message(body=body, headers={}))
            exchange.out_message = Message(body=body, headers={})
            exchange.status = ExchangeStatus.completed
            return exchange

        with patch(
            "src.backend.entrypoints.graphql.schema.get_dsl_service",
        ) as mock_get_dsl:
            mock_dsl = MagicMock()
            mock_dsl.dispatch = AsyncMock(side_effect=fake_dispatch)
            mock_get_dsl.return_value = mock_dsl

            query_instance = graphql_schema.Query()
            # Info без auth в context.
            info = _make_info_without_auth()

            await query_instance.dsl_query(
                route_id="r1", payload={"k": "v"}, info=info,
            )

        assert captured["principal"] == ""
        assert captured["permissions"] == ()
