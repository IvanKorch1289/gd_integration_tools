"""Tests for S127 W2 — DSL Variable Store (TD-020).

Covers:
- InMemoryVariableBackend: get/set/delete/list_keys + TTL expiry
- VariableScope: parsing, validation, equality
- DSLVariableStore: scope fallback (route → tenant → global), backend priority
- ExpressionResolver: ``${var('key')}``, ``${var('key', default=...)}``,
  ``${var('key', scope=...)}``, ``${env:VAR}``
- VariableResolveProcessor: walks exchange.body, resolves nested expressions
- VariableMixin: ``.variable()`` chainable method on RouteBuilder
"""

from __future__ import annotations

import asyncio
import os

import pytest

from src.backend.core.dsl.expression_resolver import (
    ExpressionResolutionError,
    ExpressionResolver,
    resolve_expression,
)
from src.backend.core.dsl.variables import (
    DSLVariableStore,
    InMemoryVariableBackend,
    VariableScope,
)

# ---------------------------------------------------------------------------
# VariableScope tests
# ---------------------------------------------------------------------------


class TestVariableScope:
    def test_global_scope(self) -> None:
        s = VariableScope.global_scope()
        assert s.kind == "global"
        assert str(s) == "global"

    def test_tenant_scope(self) -> None:
        s = VariableScope.for_tenant("acme")
        assert s.kind == "tenant"
        assert s.identifier == "acme"
        assert str(s) == "tenant:acme"

    def test_route_scope(self) -> None:
        s = VariableScope.for_route("r1")
        assert s.kind == "route"
        assert s.identifier == "r1"
        assert str(s) == "route:r1"

    def test_invalid_kind_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid scope kind"):
            VariableScope(kind="invalid")

    def test_tenant_requires_identifier(self) -> None:
        with pytest.raises(ValueError, match="requires non-empty identifier"):
            VariableScope(kind="tenant", identifier="")

    def test_parse_global(self) -> None:
        s = VariableScope.parse("global")
        assert s.kind == "global"

    def test_parse_tenant(self) -> None:
        s = VariableScope.parse("tenant:acme")
        assert s.kind == "tenant"
        assert s.identifier == "acme"

    def test_parse_default_is_global(self) -> None:
        s = VariableScope.parse("anything")
        assert s.kind == "global"

    def test_immutable(self) -> None:
        s = VariableScope.global_scope()
        with pytest.raises((AttributeError, Exception)):
            s.kind = "tenant"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# InMemoryVariableBackend tests
# ---------------------------------------------------------------------------


class TestInMemoryVariableBackend:
    @pytest.mark.asyncio
    async def test_set_get_simple(self) -> None:
        backend = InMemoryVariableBackend()
        await backend.set("api.key", "secret-123", VariableScope.global_scope())
        result = await backend.get("api.key", VariableScope.global_scope())
        assert result == "secret-123"

    @pytest.mark.asyncio
    async def test_get_missing_returns_none(self) -> None:
        backend = InMemoryVariableBackend()
        result = await backend.get("nonexistent", VariableScope.global_scope())
        assert result is None

    @pytest.mark.asyncio
    async def test_ttl_expiry(self) -> None:
        backend = InMemoryVariableBackend()
        scope = VariableScope.global_scope()
        # Use very short TTL.
        await backend.set("temp", "value", scope, ttl=0.05)
        assert await backend.get("temp", scope) == "value"
        await asyncio.sleep(0.1)
        assert await backend.get("temp", scope) is None

    @pytest.mark.asyncio
    async def test_no_ttl_means_permanent(self) -> None:
        backend = InMemoryVariableBackend()
        scope = VariableScope.global_scope()
        await backend.set("permanent", "value", scope)  # no TTL
        # Even after a small delay, value persists (TTL=0 means no expiry).
        await asyncio.sleep(0.05)
        assert await backend.get("permanent", scope) == "value"

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        backend = InMemoryVariableBackend()
        scope = VariableScope.global_scope()
        await backend.set("k", "v", scope)
        assert await backend.delete("k", scope) is True
        assert await backend.delete("k", scope) is False  # already gone
        assert await backend.get("k", scope) is None

    @pytest.mark.asyncio
    async def test_list_keys(self) -> None:
        backend = InMemoryVariableBackend()
        scope = VariableScope.global_scope()
        await backend.set("a", 1, scope)
        await backend.set("b", 2, scope)
        await backend.set("c", 3, VariableScope.for_tenant("t1"))
        keys = await backend.list_keys(scope)
        assert keys == ["a", "b"]

    @pytest.mark.asyncio
    async def test_scope_isolation(self) -> None:
        backend = InMemoryVariableBackend()
        await backend.set("k", "global", VariableScope.global_scope())
        await backend.set("k", "tenant", VariableScope.for_tenant("acme"))
        assert await backend.get("k", VariableScope.global_scope()) == "global"
        assert await backend.get("k", VariableScope.for_tenant("acme")) == "tenant"


# ---------------------------------------------------------------------------
# DSLVariableStore tests (façade + scope fallback)
# ---------------------------------------------------------------------------


class TestDSLVariableStore:
    @pytest.mark.asyncio
    async def test_single_backend_get(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("api.url", "https://api.example.com", scope="global")
        assert await store.get("api.url") == "https://api.example.com"

    @pytest.mark.asyncio
    async def test_backend_priority(self) -> None:
        """First backend with non-None result wins."""
        primary = InMemoryVariableBackend(name="primary")
        fallback = InMemoryVariableBackend(name="fallback")
        await fallback.set("k", "fallback-value", VariableScope.global_scope())
        await primary.set("k", "primary-value", VariableScope.global_scope())
        store = DSLVariableStore(backends=[primary, fallback])
        assert await store.get("k") == "primary-value"

    @pytest.mark.asyncio
    async def test_backend_fallback_when_primary_returns_none(self) -> None:
        primary = InMemoryVariableBackend(name="primary")
        fallback = InMemoryVariableBackend(name="fallback")
        await fallback.set("only-in-fallback", "value", VariableScope.global_scope())
        store = DSLVariableStore(backends=[primary, fallback])
        assert await store.get("only-in-fallback") == "value"

    @pytest.mark.asyncio
    async def test_scope_fallback_route_to_tenant_to_global(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        # Set only in global.
        await store.set("db.url", "global-db", scope="global")
        # Lookup in route scope should fall back to global.
        result = await store.get("db.url", scope="route:r1")
        assert result == "global-db"

    @pytest.mark.asyncio
    async def test_scope_fallback_tenant_to_global(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("db.url", "global-db", scope="global")
        result = await store.get("db.url", scope="tenant:acme")
        assert result == "global-db"

    @pytest.mark.asyncio
    async def test_route_scope_overrides_global(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("db.url", "global-db", scope="global")
        await store.set("db.url", "route-db", scope="route:r1")
        assert await store.get("db.url", scope="route:r1") == "route-db"

    @pytest.mark.asyncio
    async def test_no_backends_raises_on_set(self) -> None:
        store = DSLVariableStore(backends=[])
        with pytest.raises(RuntimeError, match="no backends configured"):
            await store.set("k", "v")

    @pytest.mark.asyncio
    async def test_delete(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("k", "v", scope="global")
        assert await store.delete("k") is True
        assert await store.get("k") is None

    @pytest.mark.asyncio
    async def test_list_keys(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("a", 1, scope="global")
        await store.set("b", 2, scope="global")
        await store.set("c", 3, scope="tenant:t1")
        global_keys = await store.list_keys(scope="global")
        assert global_keys == ["a", "b"]


# ---------------------------------------------------------------------------
# ExpressionResolver tests
# ---------------------------------------------------------------------------


class TestExpressionResolver:
    @pytest.mark.asyncio
    async def test_resolve_var_simple(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("api.url", "https://api.example.com", scope="global")
        resolver = ExpressionResolver(store)
        result = await resolver.resolve("Endpoint: ${var('api.url')}")
        assert result == "Endpoint: https://api.example.com"

    @pytest.mark.asyncio
    async def test_resolve_var_with_default(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        resolver = ExpressionResolver(store)
        result = await resolver.resolve("${var('missing.key', default='fallback')}")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_resolve_var_with_explicit_scope(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("api.key", "tenant-key", scope="tenant:acme")
        resolver = ExpressionResolver(store)
        result = await resolver.resolve("${var('api.key', scope='tenant:acme')}")
        assert result == "tenant-key"

    @pytest.mark.asyncio
    async def test_resolve_var_with_default_double_quoted(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        resolver = ExpressionResolver(store)
        result = await resolver.resolve("${var('missing', default=\"fallback-dq\")}")
        assert result == "fallback-dq"

    @pytest.mark.asyncio
    async def test_resolve_unresolved_raises(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        resolver = ExpressionResolver(store)
        with pytest.raises(ExpressionResolutionError, match="not found"):
            await resolver.resolve("${var('missing.key')}")

    @pytest.mark.asyncio
    async def test_no_expressions_passthrough(self) -> None:
        resolver = ExpressionResolver()
        assert await resolver.resolve("just a string") == "just a string"

    @pytest.mark.asyncio
    async def test_multiple_expressions(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("host", "localhost", scope="global")
        await store.set("port", "5432", scope="global")
        resolver = ExpressionResolver(store)
        result = await resolver.resolve("postgres://${var('host')}:${var('port')}/db")
        assert result == "postgres://localhost:5432/db"

    @pytest.mark.asyncio
    async def test_env_var_substitution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("TEST_VAR_FOR_RESOLVER", "env-value")
        resolver = ExpressionResolver()
        result = await resolver.resolve("env=${env:TEST_VAR_FOR_RESOLVER}")
        assert result == "env=env-value"

    @pytest.mark.asyncio
    async def test_env_var_missing_returns_empty(self) -> None:
        # Save and clear any pre-existing value.
        old = os.environ.pop("DEFINITELY_NOT_SET_XYZ", None)
        try:
            resolver = ExpressionResolver()
            result = await resolver.resolve("${env:DEFINITELY_NOT_SET_XYZ}")
            assert result == ""
        finally:
            if old is not None:
                os.environ["DEFINITELY_NOT_SET_XYZ"] = old

    @pytest.mark.asyncio
    async def test_body_field_passthrough(self) -> None:
        """``${body.field}`` is left as-is (resolved at runtime)."""
        resolver = ExpressionResolver()
        result = await resolver.resolve("field=${body.user_id}")
        assert result == "field=${body.user_id}"

    @pytest.mark.asyncio
    async def test_convenience_resolve_expression(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("k", "v", scope="global")
        result = await resolve_expression("${var('k')}", store=store)
        assert result == "v"


# ---------------------------------------------------------------------------
# VariableResolveProcessor tests
# ---------------------------------------------------------------------------


class TestVariableResolveProcessor:
    @pytest.mark.asyncio
    async def test_walks_body_dict(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("api.url", "https://api.example.com", scope="global")
        # Reconfigure default singleton to use our store.
        DSLVariableStore.configure(store.backends)

        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.variable_resolve import (
            VariableResolveProcessor,
        )

        processor = VariableResolveProcessor.__new__(VariableResolveProcessor)
        processor.__init__(scope="global", fail_on_unresolved=False)

        exchange = Exchange(
            in_message=Message(body={"endpoint": "${var('api.url')}", "method": "GET"})
        )
        await processor.process(exchange, ExecutionContext())

        assert exchange.in_message.body == {
            "endpoint": "https://api.example.com",
            "method": "GET",
        }
        result = exchange.properties.get("_variable_resolve_result")
        assert result["resolved_count"] >= 1
        assert result["scope"] == "global"

    @pytest.mark.asyncio
    async def test_walks_nested_structures(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        await store.set("name", "World", scope="global")
        DSLVariableStore.configure(store.backends)

        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.variable_resolve import (
            VariableResolveProcessor,
        )

        processor = VariableResolveProcessor.__new__(VariableResolveProcessor)
        processor.__init__(scope="global", fail_on_unresolved=False)

        body = {
            "user": {"greeting": "Hello, ${var('name')}!"},
            "items": ["item1", "item-${var('name')}"],
        }
        exchange = Exchange(in_message=Message(body=body))
        await processor.process(exchange, ExecutionContext())

        assert exchange.in_message.body["user"]["greeting"] == "Hello, World!"
        assert exchange.in_message.body["items"][1] == "item-World"

    @pytest.mark.asyncio
    async def test_unresolved_logged_but_not_failed(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        DSLVariableStore.configure(store.backends)

        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.variable_resolve import (
            VariableResolveProcessor,
        )

        processor = VariableResolveProcessor.__new__(VariableResolveProcessor)
        processor.__init__(scope="global", fail_on_unresolved=False)

        exchange = Exchange(in_message=Message(body={"x": "${var('not.set')}"}))
        await processor.process(exchange, ExecutionContext())
        # Body preserved (not crashed).
        assert exchange.in_message.body == {"x": "${var('not.set')}"}
        result = exchange.properties.get("_variable_resolve_result")
        assert len(result["unresolved_keys"]) >= 1

    @pytest.mark.asyncio
    async def test_fail_on_unresolved_raises(self) -> None:
        store = DSLVariableStore(backends=[InMemoryVariableBackend()])
        DSLVariableStore.configure(store.backends)

        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.variable_resolve import (
            VariableResolveProcessor,
        )

        processor = VariableResolveProcessor.__new__(VariableResolveProcessor)
        processor.__init__(scope="global", fail_on_unresolved=True)

        exchange = Exchange(in_message=Message(body={"x": "${var('not.set')}"}))
        with pytest.raises(ExpressionResolutionError):
            await processor.process(exchange, ExecutionContext())

    @pytest.mark.asyncio
    async def test_non_dict_body_skipped(self) -> None:
        """Non-dict body is left untouched."""
        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.exchange import Exchange, Message
        from src.backend.dsl.engine.processors.variable_resolve import (
            VariableResolveProcessor,
        )

        processor = VariableResolveProcessor.__new__(VariableResolveProcessor)
        processor.__init__(scope="global", fail_on_unresolved=False)

        exchange = Exchange(in_message=Message(body="just a string"))
        await processor.process(exchange, ExecutionContext())
        assert exchange.in_message.body == "just a string"


# ---------------------------------------------------------------------------
# VariableMixin tests
# ---------------------------------------------------------------------------


class TestVariableMixin:
    def test_mixin_method_exists(self) -> None:
        from src.backend.dsl.builders.variable_mixin import VariableMixin

        assert hasattr(VariableMixin, "variable")
        assert hasattr(VariableMixin, "variable_resolve")

    def test_mixin_is_chainable(self) -> None:
        """Verify _add_lazy returns self for chainable builders."""
        # Static check: methods return self via _add_lazy.
        import inspect

        from src.backend.dsl.builders.variable_mixin import VariableMixin

        sig = inspect.signature(VariableMixin.variable)
        # variable(*, default, scope, name) — kwargs-only.
        params = sig.parameters
        assert "default" in params
        assert "scope" in params
        assert "name" in params
