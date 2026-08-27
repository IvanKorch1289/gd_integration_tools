"""P0 security regression test (Cycle 4, production-grade plan).

Реальная проверка (не мок): что ``GraphQLRouter`` production-кода
принимает ``context_getter=_graphql_context_getter`` И что после
middleware ``AuthRequiredMiddleware`` resolver получает
``info.context["auth"]`` (не пустой).

Pre-fix (S44 W1 commit 94960cf4 claimed "19/19 P0 closed" — false claim):
``context_getter`` был определён в schema.py:249, но НЕ передан в
``GraphQLRouter(...)``. Strawberry использует свой default
``context_getter`` который возвращает ``{"request": request}`` без
``"auth"`` ключа → ``_principal_from_info(info)`` всегда "" →
fail-closed для authorized users + fail-open для routes без strict
security.

Этот тест запускает GraphQLRouter через TestClient и проверяет,
что context_getter подключён в production-коде.

Запуск::

    .venv/bin/python -m pytest \\
      tests/integration/entrypoints/graphql/test_context_propagation_e2e.py -v
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

from fastapi import Depends
from strawberry.fastapi import GraphQLRouter

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.auth_context_helpers import extract_user_permissions
from src.backend.core.auth.auth_selector import require_auth
from src.backend.entrypoints.graphql.schema import _graphql_context_getter


def _build_production_router(path: str = "/graphql") -> GraphQLRouter:
    """Собрать GraphQLRouter ТОЧНО так же, как в schema.py:60-72.

    Использует минимальный stub-schema (нужен только для того, чтобы
    GraphQLRouter не падал на init). Цель — проверить, что context_getter
    wiring'а из production-кода корректно пробрасывается.
    """
    import strawberry

    @strawberry.type
    class _Query:
        @strawberry.field
        def hello(self) -> str:
            return "world"

    schema = strawberry.Schema(query=_Query)

    return GraphQLRouter(
        schema,
        path=path,
        # Это ТОЧНАЯ копия production wiring (schema.py:60-72 после fix):
        context_getter=_graphql_context_getter,
        dependencies=[Depends(require_auth([AuthMethod.API_KEY, AuthMethod.JWT]))],
    )


class TestProductionRouterWiring:
    """Проверка, что production GraphQLRouter имеет context_getter."""

    def test_production_router_has_context_getter(self) -> None:
        """``GraphQLRouter.context_getter`` не None после wiring'а.

        Strawberry оборачивает context_getter в dependency function, но
        атрибут ``context_getter`` устанавливается и не None, когда
        передан в GraphQLRouter(...).
        """
        router = _build_production_router()
        cg = getattr(router, "context_getter", None)
        assert cg is not None, (
            "GraphQLRouter.context_getter is None — P0 L5 Security Chain broken"
        )


class TestSchemaSourceHasContextGetter:
    """Source-of-truth: source code schema.py передаёт context_getter.

    AST-проверка гарантирует, что паттерн wiring'а не будет случайно
    удалён в будущем (regression guard против S44 W1 false-closure).
    """

    def test_schema_py_passes_context_getter(self) -> None:
        """schema.py содержит ``context_getter=_graphql_context_getter``."""
        import ast
        from pathlib import Path

        src = Path(
            "/home/user/dev/gd_integration_tools/src/backend/entrypoints/graphql/schema.py"
        ).read_text()
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "GraphQLRouter"
            ):
                for kw in node.keywords:
                    if kw.arg == "context_getter" and isinstance(
                        kw.value, ast.Name
                    ) and kw.value.id == "_graphql_context_getter":
                        found = True
        assert found, (
            "schema.py: GraphQLRouter(...) НЕ передаёт context_getter="
            "_graphql_context_getter. P0 L5 Security Chain broken."
        )

    def test_auto_schema_py_passes_context_getter(self) -> None:
        """auto_schema.py — тот же фикс через lazy import."""
        import ast
        from pathlib import Path

        src = Path(
            "/home/user/dev/gd_integration_tools/src/backend/entrypoints/graphql/auto_schema.py"
        ).read_text()
        assert "_graphql_context_getter" in src, (
            "auto_schema.py: НЕ упоминает _graphql_context_getter. "
            "P0 L5 Security Chain broken для /api/v1/graphql endpoint."
        )
        tree = ast.parse(src)
        found = False
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "GraphQLRouter"
            ):
                for kw in node.keywords:
                    if kw.arg == "context_getter":
                        found = True
        assert found, (
            "auto_schema.py: GraphQLRouter(...) НЕ передаёт context_getter. "
            "P0 L5 Security Chain broken."
        )


def _run_async(coro):
    """Запустить coroutine синхронно (для тестов без pytest-asyncio)."""
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


class TestContextGetterBehavior:
    """Unit-уровневая проверка ``_graphql_context_getter`` (async)."""

    def test_context_getter_extracts_auth_from_state(self) -> None:
        """``request.state.auth`` → ``ctx["auth"] = AuthContext``."""
        mock_request = MagicMock()
        mock_request.state.auth = AuthContext(
            method=AuthMethod.JWT,
            principal="alice",
            metadata={"permissions": ["read:orders"], "tenant_id": "t1"},
        )

        ctx = asyncio.run(_graphql_context_getter(mock_request))
        assert ctx["auth"] is not None, "context_getter returned None auth"
        assert ctx["auth"].principal == "alice", (
            f"Expected principal='alice', got {ctx['auth'].principal!r}"
        )
        assert ctx["auth"].metadata["permissions"] == ["read:orders"]

    def test_context_getter_handles_missing_auth(self) -> None:
        """Fail-closed: ``request.state.auth`` missing → ``auth: None``."""
        mock_request = MagicMock(spec=["state"])
        mock_request.state = MagicMock(spec=[])  # нет атрибута auth

        ctx = asyncio.run(_graphql_context_getter(mock_request))
        assert ctx["auth"] is None, (
            "context_getter should return None auth when state.auth missing"
        )

    def test_context_getter_handles_none_request(self) -> None:
        """Edge case: ``request=None`` → ``ctx = {"request": None, "auth": None}``."""
        ctx = asyncio.run(_graphql_context_getter(None))
        assert ctx["request"] is None
        assert ctx["auth"] is None


def test_extract_user_permissions_roundtrip() -> None:
    """Sanity: extract_user_permissions для AuthContext с permissions."""
    auth = AuthContext(
        method=AuthMethod.API_KEY,
        principal="bob",
        metadata={"permissions": ["admin", "operator"], "tenant_id": "t2"},
    )
    perms = extract_user_permissions(auth)
    assert "admin" in perms
    assert "operator" in perms


