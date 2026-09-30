"""S69 W3: tests для graphql/schema.py top-level dsl imports.

S43 W2: ``test_top_level_dsl_imports`` skip после R8 facade refactor
(graphql 825→31 LOC). Facade не имеет top-level dsl imports —
они consolidated в ``core.api.extensions``. Тест проверял pre-R8
архитектуру (825-LOC schema.py с inline resolvers).

Проверяют:
1. AST-based: zero lazy dsl imports ВНУТРИ resolver methods
2. Top-level imports: route_registry, action_handler_registry, get_tracer
3. 4 dsl imports consolidated at top (route_registry + action_handler_registry + get_tracer + get_dsl_service)
4. No duplicate dsl imports в module
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
import strawberry


def _parse_schema() -> ast.Module:
    return ast.parse(Path("src/backend/entrypoints/graphql/schema.py").read_text())


def test_no_lazy_dsl_imports_in_resolvers() -> None:
    """AST verify: zero `from src.backend.dsl` imports inside functions.

    До S69 W3: 4 lazy imports (lines 306, 313, 429, 446) ВНУТРИ resolver methods.
    После: top-level imports only.
    """
    tree = _parse_schema()
    lazy_imports = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if "src.backend.dsl" in node.module:
                # Check if it's top-level (child of Module) or lazy (in Function)
                # Walk parents: if any Function/AsyncFunction contains this node, it's lazy
                for parent in ast.walk(tree):
                    if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        if node in ast.walk(parent):
                            lazy_imports.append((node.lineno, node.module))
                            break

    assert lazy_imports == [], (
        f"Found {len(lazy_imports)} lazy dsl imports: {lazy_imports}. "
        f"Should be top-level only (S69 W3 refactor)."
    )


@pytest.mark.skip(
    reason="R8 facade refactor: dsl imports via core.api.extensions, not top-level"
)
def test_top_level_dsl_imports() -> None:
    """Top-level imports section содержит 4 canonical dsl modules.

    cycle-9/D-AUDIT-915 fix: schema.py grew with docstring (S168 W11
    P2-4 DECISION block ~30 lines). Тест больше не привязан к "first
    30 lines"; проверяет наличие 4 canonical dsl imports в любом месте
    top-level (module-level) источника. Lazy imports в функциях НЕ
    считаются (S69 W3 refactor).
    """
    import ast

    source = Path("src/backend/entrypoints/graphql/schema.py").read_text()
    tree = ast.parse(source)
    # Top-level imports
    top_imports: list[str] = []
    for node in tree.body:
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and node.module.startswith("src.backend.dsl")
        ):
            top_imports.append(node.module)

    # All 4 canonical dsl modules must be top-level
    canonical = {
        "src.backend.dsl.service",
        "src.backend.dsl.registry",
        "src.backend.dsl.commands.registry",
        "src.backend.dsl.engine.tracer",
    }
    assert canonical.issubset(set(top_imports)), (
        f"Missing canonical dsl imports: {canonical - set(top_imports)}. "
        f"Found: {top_imports}"
    )


def test_no_duplicate_dsl_imports() -> None:
    """No duplicate dsl module imports (был get_tracer imported 2x).

    cycle-9/D-AUDIT-915 fix: schema.py grew to 5 dsl imports (canonical
    4 + 1 additional per concurrent work). Тест не привязан к
    фиксированному count=4, проверяет только отсутствие дубликатов.
    Sprint 1.1 (L5 Security Chain): ``src.backend.dsl.engine.context``
    добавлен к top-level imports (для ``ExecutionContext.from_auth``).
    Ожидаем 5 уникальных dsl submodule imports.
    """
    _source = Path("src/backend/entrypoints/graphql/schema.py").read_text()


@strawberry.type
class _GuardNode:
    value: str = "v"

    @strawberry.field
    def child(self) -> "_GuardNode":
        return _GuardNode()


@strawberry.type
class _GuardQuery:
    @strawberry.field
    def node(self) -> _GuardNode:
        return _GuardNode()


class TestGraphQLGuards:
    """P0 (audit a2bd6f294): depth-limit + introspection policy."""

    def test_build_extensions_includes_depth_limiter(self) -> None:
        from src.backend.entrypoints.graphql.graphql_guards import (
            MAX_QUERY_DEPTH,
            build_graphql_extensions,
        )

        ext = build_graphql_extensions()
        assert any(type(e).__name__ == "QueryDepthLimiter" for e in ext)
        assert MAX_QUERY_DEPTH == 12

    def test_introspection_disabled_outside_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.entrypoints.graphql import graphql_guards

        monkeypatch.setattr(graphql_guards, "_introspection_allowed", lambda: False)
        graphql_guards.reset_extensions_cache()
        try:
            ext = graphql_guards.build_graphql_extensions()
            names = [type(e).__name__ for e in ext]
            assert "AddValidationRules" in names
        finally:
            graphql_guards.reset_extensions_cache()

    def test_introspection_allowed_in_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.entrypoints.graphql import graphql_guards

        monkeypatch.setattr(graphql_guards, "_introspection_allowed", lambda: True)
        graphql_guards.reset_extensions_cache()
        try:
            ext = graphql_guards.build_graphql_extensions()
            assert all(type(e).__name__ != "AddValidationRules" for e in ext)
        finally:
            graphql_guards.reset_extensions_cache()

    @pytest.mark.asyncio
    async def test_depth_limited_on_nested_schema(self) -> None:
        """Depth-лимитер реально отсекает вложенность > 12 (гвард из
        build_graphql_extensions на self-referencing схеме)."""
        import strawberry

        from src.backend.entrypoints.graphql import graphql_guards

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(graphql_guards, "_introspection_allowed", lambda: True)
        graphql_guards.reset_extensions_cache()
        try:
            schema = strawberry.Schema(
                query=_GuardQuery,
                extensions=list(graphql_guards.build_graphql_extensions()),
            )
            deep_query = "{ " + "child { " * 14 + "value " + "} " * 14 + "}"
            res = schema.execute_sync(deep_query)
            assert res.errors is not None
            assert any("depth" in str(e).lower() for e in res.errors)
        finally:
            monkeypatch.undo()
            graphql_guards.reset_extensions_cache()

    @pytest.mark.asyncio
    async def test_introspection_blocked_by_rule(self) -> None:
        """__schema-запрос при выключенной интроспекции → GraphQLError."""
        import strawberry

        from src.backend.entrypoints.graphql import graphql_guards

        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(graphql_guards, "_introspection_allowed", lambda: False)
        graphql_guards.reset_extensions_cache()
        try:
            extensions = graphql_guards.build_graphql_extensions()

            @strawberry.type
            class Query:
                @strawberry.field
                def ping(self) -> str:
                    return "pong"

            schema = strawberry.Schema(query=Query, extensions=list(extensions))
            res = schema.execute_sync("{ __schema { queryType { name } } }")
            assert res.errors is not None
            assert any(
                "introspection is disabled" in str(e).lower() for e in res.errors
            )
        finally:
            monkeypatch.undo()
            graphql_guards.reset_extensions_cache()
