"""S127 W2 — DSL expression resolver for `${var('key')}` syntax.

Supports the Airflow-style variable substitution syntax:
- `${var('key')}` — resolve from DSLVariableStore (scope=global)
- `${var('key', scope='tenant:acme')}` — explicit scope
- `${var('key', default='fallback')}` — default value if not found
- `${body.field}` — body reference (passthrough to existing resolver)
- `${properties.key}` — properties reference (passthrough)
- `${env:VAR_NAME}` — environment variable (passthrough)
- `${secret:vault/path}` — Vault secret (passthrough)

Pattern: regex-based scan of a string + replace each `${...}` token.
Tokens that can't be resolved raise ``ExpressionResolutionError`` —
unless a default is provided.
"""

from __future__ import annotations

import os
import re
from typing import Any

from src.backend.core.dsl.variables import DSLVariableStore, VariableScope
from src.backend.core.logging import get_logger

__all__ = ("ExpressionResolver", "ExpressionResolutionError", "resolve_expression")

_logger = get_logger("core.dsl.expression_resolver")


# Pattern for `${var('key', scope='tenant:acme', default='x')}`.
# Captures: 1=key, 2=scope (optional), 3=default (optional).
_VAR_PATTERN = re.compile(
    r"\$\{var\(\s*"
    r"'([^']+)'"  # key (single-quoted)
    r"(?:\s*,\s*scope\s*=\s*'([^']+)')?"  # optional scope
    r"(?:\s*,\s*default\s*=\s*('[^']*'|\"([^\"]*)\"))?"  # optional default
    r"\s*\)\}"
)


class ExpressionResolutionError(ValueError):
    """Raised when an expression cannot be resolved and no default provided."""


class ExpressionResolver:
    """Async resolver for `${...}` expressions in DSL strings.

    Stateless and side-effect-free: ``resolve(s)`` is purely functional
    given a ``DSLVariableStore`` reference.
    """

    def __init__(self, variable_store: DSLVariableStore | None = None) -> None:
        self._store = variable_store or DSLVariableStore.get_default()

    async def resolve(self, value: str) -> str:
        """Resolve all `${...}` expressions in a string.

        Args:
            value: String with embedded expressions (e.g.,
                ``"url=${var('db.url')}"``).

        Returns:
            String with all expressions replaced.

        Raises:
            ExpressionResolutionError: If an expression cannot be
                resolved and no default is provided.
        """
        if "${" not in value:
            return value  # Fast path: no expressions.

        # 1. ${var('key', scope=..., default=...)} — primary path.
        async def _replace_var(match: re.Match[str]) -> str:
            key = match.group(1)
            scope_str = match.group(2) or "global"
            default_quoted = match.group(3) or match.group(4)
            scope = VariableScope.parse(scope_str)
            resolved = await self._store.get(key, scope)
            if resolved is None:
                if default_quoted is not None:
                    # Strip surrounding quotes from the captured default.
                    if default_quoted.startswith(("'", '"')):
                        return default_quoted[1:-1]
                    return default_quoted
                raise ExpressionResolutionError(
                    f"Variable {key!r} not found in scope {scope_str!r} "
                    f"(no default provided)"
                )
            return str(resolved)

        value = await _async_sub(_VAR_PATTERN, value, _replace_var)

        # 2. ${body.field} — passthrough (resolved at runtime by
        # existing exchange.body resolver; leave as-is).
        # 3. ${properties.key} — passthrough.
        # 4. ${env:VAR_NAME} — resolve here.
        value = _resolve_env(value)
        # 5. ${secret:vault/path} — passthrough (resolved by SecretsResolver
        # at runtime; only tokenize the path).

        return value


async def resolve_expression(value: str, store: DSLVariableStore | None = None) -> str:
    """Convenience: single-expression resolve via default store."""
    return await ExpressionResolver(store).resolve(value)


def _resolve_env(value: str) -> str:
    """Replace ${env:VAR_NAME} with ``os.environ[VAR_NAME]`` (or empty)."""

    def _sub_env(match: re.Match[str]) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")

    return re.sub(r"\$\{env:([A-Z_][A-Z0-9_]*)\}", _sub_env, value)


async def _async_sub(pattern: re.Pattern[str], value: str, replace: Any) -> str:
    """Async version of ``re.sub`` (since replace is async)."""
    result: list[str] = []
    last_end = 0
    for match in pattern.finditer(value):
        result.append(value[last_end : match.start()])
        replacement = await replace(match)
        result.append(replacement)
        last_end = match.end()
    result.append(value[last_end:])
    return "".join(result)
