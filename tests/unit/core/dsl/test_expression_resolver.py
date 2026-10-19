"""Tests for ``src.backend.core.dsl.expression_resolver``.

S127 W2: Async DSL expression resolver для ``${var('key')}`` syntax.
Поддерживает var() expressions, env:VAR_NAME, passthrough для
body/properties/secret.

Использует InMemoryVariableBackend или fake для unit-тестов.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

import pytest

from src.backend.core.dsl.expression_resolver import (
    ExpressionResolutionError,
    ExpressionResolver,
    resolve_expression,
)
from src.backend.core.dsl.variables import DSLVariableStore, VariableScope


# ── Fake variable store ────────────────────────────────────────────


class _FakeBackend:
    """Простой in-memory backend для тестов."""

    def __init__(self) -> None:
        self._data: dict[tuple[str, str], Any] = {}

    def set(self, key: str, value: Any, scope: VariableScope | str = "global") -> None:
        scope_str = str(scope)
        self._data[(scope_str, key)] = value

    async def get(self, key: str, scope: VariableScope | str = "global") -> Any:
        scope_str = str(scope)
        if (scope_str, key) in self._data:
            return self._data[(scope_str, key)]
        # Fallback: global
        if (VariableScope.global_scope().__str__(), key) in self._data:
            return self._data[(VariableScope.global_scope().__str__(), key)]
        return None


def _make_store() -> tuple[DSLVariableStore, _FakeBackend]:
    """Возвращает (store, fake_backend) для удобства тестов."""
    fake = _FakeBackend()
    store = DSLVariableStore(backends=[fake])
    return store, fake


# ── ExpressionResolutionError ───────────────────────────────────────


class TestExpressionResolutionError:
    """Custom exception — ValueError subclass."""

    def test_is_value_error(self) -> None:
        assert issubclass(ExpressionResolutionError, ValueError)

    def test_can_be_raised(self) -> None:
        with pytest.raises(ExpressionResolutionError):
            raise ExpressionResolutionError("test")

    def test_message_preserved(self) -> None:
        err = ExpressionResolutionError("var 'x' not found")
        assert "var 'x' not found" in str(err)


# ── ExpressionResolver.__init__ ──────────────────────────────────────


class TestExpressionResolverInit:
    """Constructor: optional variable_store."""

    def test_init_with_default_store(self) -> None:
        """``__init__()`` без аргументов → ``DSLVariableStore.get_default()``."""
        resolver = ExpressionResolver()
        assert resolver._store is not None

    def test_init_with_explicit_store(self) -> None:
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        assert resolver._store is store

    def test_init_with_none_uses_default(self) -> None:
        """``variable_store=None`` — fallback to default."""
        resolver = ExpressionResolver(variable_store=None)
        assert resolver._store is not None


# ── ExpressionResolver.resolve ──────────────────────────────────────


class TestExpressionResolverResolve:
    """Async ``resolve(value)`` — replace ${...} expressions."""

    @pytest.mark.asyncio
    async def test_no_expressions_returns_as_is(self) -> None:
        """Fast path: string без ``${`` — возвращается как есть."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("plain text without vars")
        assert result == "plain text without vars"

    @pytest.mark.asyncio
    async def test_empty_string(self) -> None:
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("")
        assert result == ""

    @pytest.mark.asyncio
    async def test_resolve_simple_var(self) -> None:
        """``${var('key')}`` — resolve from store."""
        store, fake = _make_store()
        fake.set("db.url", "postgres://localhost/db")
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('db.url')}")
        assert result == "postgres://localhost/db"

    @pytest.mark.asyncio
    async def test_resolve_var_in_template(self) -> None:
        """``url=${var('db.url')}&timeout=30`` — partial replace."""
        store, fake = _make_store()
        fake.set("db.url", "postgres://x")
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("url=${var('db.url')}&timeout=30")
        assert result == "url=postgres://x&timeout=30"

    @pytest.mark.asyncio
    async def test_resolve_with_default(self) -> None:
        """``${var('missing', default='fallback')}`` → fallback."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('missing', default='fallback')}")
        assert result == "fallback"

    @pytest.mark.asyncio
    async def test_resolve_with_extra_whitespace(self) -> None:
        """Extra whitespace в params — regex всё равно сматчит."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var( 'k' , default='fb' )}")
        assert result == "fb"

    @pytest.mark.asyncio
    async def test_resolve_with_tenant_scope(self) -> None:
        """``scope='tenant:acme'`` — lookup в tenant scope."""
        store, fake = _make_store()
        fake.set("k", "tenant-value", VariableScope.for_tenant("acme"))
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('k', scope='tenant:acme')}")
        assert result == "tenant-value"

    @pytest.mark.asyncio
    async def test_resolve_with_route_scope(self) -> None:
        """``scope='route:r1'`` — lookup в route scope."""
        store, fake = _make_store()
        fake.set("k", "route-value", VariableScope.for_route("r1"))
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('k', scope='route:r1')}")
        assert result == "route-value"

    @pytest.mark.asyncio
    async def test_missing_var_no_default_raises(self) -> None:
        """Variable not found + no default → ``ExpressionResolutionError``."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        with pytest.raises(ExpressionResolutionError) as exc_info:
            await resolver.resolve("${var('missing')}")
        assert "missing" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_multiple_vars_in_one_string(self) -> None:
        """Несколько var() в одной строке — все заменяются."""
        store, fake = _make_store()
        fake.set("a", "1")
        fake.set("b", "2")
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('a')}-${var('b')}")
        assert result == "1-2"

    @pytest.mark.asyncio
    async def test_int_value_converted_to_str(self) -> None:
        """``str(resolved)`` — int → "42"."""
        store, fake = _make_store()
        fake.set("port", 5432)
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('port')}")
        assert result == "5432"

    @pytest.mark.asyncio
    async def test_default_with_quotes_in_value(self) -> None:
        """Default с internal quotes — strip surrounding quotes."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        # Single-quoted default с value 'fallback'
        result = await resolver.resolve("${var('x', default='fallback')}")
        assert result == "fallback"


# ── resolve_expression convenience ──────────────────────────────────


class TestResolveExpression:
    """Module-level ``resolve_expression`` convenience function."""

    @pytest.mark.asyncio
    async def test_with_explicit_store(self) -> None:
        store, fake = _make_store()
        fake.set("k", "v")
        result = await resolve_expression("${var('k')}", store=store)
        assert result == "v"

    @pytest.mark.asyncio
    async def test_without_store_uses_default(self) -> None:
        """``store=None`` → ``DSLVariableStore.get_default()``.

        Default store обычно пустой → raises. Тест проверяет, что
        исключение — от default store, не от None.
        """
        with pytest.raises(ExpressionResolutionError):
            await resolve_expression("${var('nonexistent-key-12345')}")

    @pytest.mark.asyncio
    async def test_no_expressions(self) -> None:
        result = await resolve_expression("plain text")
        assert result == "plain text"


# ── env:VAR_NAME ────────────────────────────────────────────────────


class TestEnvResolution:
    """``${env:VAR_NAME}`` — resolve через os.environ."""

    @pytest.mark.asyncio
    async def test_resolves_existing_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Установленный env var — подставляется в результат."""
        monkeypatch.setenv("MY_TEST_VAR", "test-value")
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${env:MY_TEST_VAR}")
        assert result == "test-value"

    @pytest.mark.asyncio
    async def test_missing_env_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Отсутствующий env var → пустая строка (не raise)."""
        monkeypatch.delenv("DEFINITELY_NOT_SET_VAR_12345", raising=False)
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${env:DEFINITELY_NOT_SET_VAR_12345}")
        assert result == ""

    @pytest.mark.asyncio
    async def test_env_in_template(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """``prefix=${env:VAR}/suffix`` — partial replace."""
        monkeypatch.setenv("HOST", "example.com")
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("https://${env:HOST}/api")
        assert result == "https://example.com/api"

    @pytest.mark.asyncio
    async def test_env_with_lowercase_name_not_matched(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Regex требует uppercase: ``${env:lowercase}`` — не match."""
        monkeypatch.setenv("lowercase", "value")
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        # Regex: [A-Z_][A-Z0-9_]* — lowercase не совпадает
        result = await resolver.resolve("${env:lowercase}")
        # Остаётся как есть (regex не сматчил)
        assert result == "${env:lowercase}"


# ── passthrough tokens (body/properties/secret) ────────────────────


class TestPassthroughTokens:
    """``${body.x}``, ``${properties.x}``, ``${secret:x}`` — passthrough."""

    @pytest.mark.asyncio
    async def test_body_passthrough(self) -> None:
        """``${body.field}`` — оставляется как есть."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${body.user_id}")
        assert result == "${body.user_id}"

    @pytest.mark.asyncio
    async def test_properties_passthrough(self) -> None:
        """``${properties.key}`` — passthrough."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${properties.timeout}")
        assert result == "${properties.timeout}"

    @pytest.mark.asyncio
    async def test_secret_passthrough(self) -> None:
        """``${secret:vault/path}`` — passthrough (resolved by SecretsResolver)."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${secret:db/password}")
        assert result == "${secret:db/password}"

    @pytest.mark.asyncio
    async def test_mixed_var_and_passthrough(self) -> None:
        """``${var('x')} + ${body.y}`` — var resolved, body passthrough."""
        store, fake = _make_store()
        fake.set("x", "value-x")
        resolver = ExpressionResolver(variable_store=store)
        result = await resolver.resolve("${var('x')} and ${body.y}")
        assert result == "value-x and ${body.y}"


# ── VariableScope.parse edge cases ──────────────────────────────────


class TestVariableScopeParseIntegration:
    """``scope_str`` → ``VariableScope`` — edge cases."""

    @pytest.mark.asyncio
    async def test_invalid_scope_raises(self) -> None:
        """Invalid scope string (без ``:``) → ValueError from VariableScope.parse."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        with pytest.raises(ValueError):
            await resolver.resolve("${var('x', scope='not-a-scope')}")

    @pytest.mark.asyncio
    async def test_scope_with_empty_identifier_raises(self) -> None:
        """``scope='tenant:'`` — empty identifier → ValueError."""
        store, _ = _make_store()
        resolver = ExpressionResolver(variable_store=store)
        with pytest.raises(ValueError):
            await resolver.resolve("${var('x', scope='tenant:')}")


# ── __all__ exports ─────────────────────────────────────────────────


class TestExpressionResolverExports:
    """Module ``__all__``."""

    def test_exports(self) -> None:
        from src.backend.core.dsl import expression_resolver

        assert set(expression_resolver.__all__) == {
            "ExpressionResolutionError",
            "ExpressionResolver",
            "resolve_expression",
        }
