"""S127 W2 — VariableResolveProcessor (DSL processor for var resolution).

DSL step ``variable_resolve``: walks the entire exchange.body tree and
resolves all ``${var('key')}`` expressions via the default
:class:`DSLVariableStore`.

Example YAML DSL::

    steps:
      - variable_resolve:
          scope: global  # or tenant:<id>, route:<id>
        output: { resolved_body: dict }

Example Python DSL::

    from src.backend.dsl.builders import RouteBuilder
    builder.variable_resolve(scope="global")
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, ClassVar

from src.backend.core.dsl.expression_resolver import (
    ExpressionResolver,
    ExpressionResolutionError,
)
from src.backend.core.dsl.variables import DSLVariableStore, VariableScope
from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_logger = get_logger("dsl.processor.variable_resolve")

__all__ = ("VariableResolveResult", "VariableResolveProcessor")


@dataclass
class VariableResolveResult:
    """Summary of variable resolution for one exchange.body.

    Attributes:
        resolved_count: Number of ``${var('...')}`` expressions resolved.
        unresolved_keys: Keys that couldn't be resolved (no default).
        scope: The scope used for resolution.
    """

    resolved_count: int
    unresolved_keys: list[str]
    scope: str


class VariableResolveProcessor(BaseProcessor):
    """Walk exchange.body и resolve ``${var('...')}`` expressions.

    Args:
        scope: Scope for variable lookup (``"global"``,
            ``"tenant:acme"``, ``"route:r1"``). По умолчанию
            ``"global"``. Если ``"tenant:current"`` — используется
            tenant из execution context.
        fail_on_unresolved: Если True, ошибка на unresolved переменных
            (без default). Default False (только логируем).
        name: Имя процессора для трассировки.

    Body contract: dict с произвольной структурой (string values могут
    содержать ``${var('...')}``).
    Output: ``exchange.body`` — dict с resolved values;
    ``exchange.properties["_variable_resolve_result"]`` —
    :class:`VariableResolveResult` summary.

    Example::

        builder.variable_resolve(scope="tenant:acme", fail_on_unresolved=False)
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        scope: str = "global",
        fail_on_unresolved: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"variable_resolve:{scope}")
        self._scope = scope
        self._fail_on_unresolved = fail_on_unresolved
        self._resolver: ExpressionResolver | None = None

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, dict):
            _logger.debug("variable_resolve: body is not dict, skipping")
            return

        store = DSLVariableStore.get_default()
        self._resolver = ExpressionResolver(store)

        scope = self._resolve_actual_scope(context)
        resolver = self._resolver

        resolved_count = 0
        unresolved: list[str] = []

        async def _walk_and_resolve(node: Any) -> Any:
            nonlocal resolved_count
            if isinstance(node, str):
                if "${var(" in node:
                    try:
                        # For walk: regex needs to know scope, so we
                        # do simple substitution here.
                        replaced = await self._resolve_in_string(node, resolver, scope)
                        resolved_count += node.count("${var(") - replaced.count("${var(")
                        return replaced
                    except ExpressionResolutionError as exc:
                        unresolved.append(str(exc))
                        if self._fail_on_unresolved:
                            raise
                        return node
                return node
            if isinstance(node, dict):
                return {k: await _walk_and_resolve(v) for k, v in node.items()}
            if isinstance(node, list):
                return [await _walk_and_resolve(item) for item in node]
            return node

        new_body = await _walk_and_resolve(body)
        exchange.in_message.body = new_body
        exchange.set_property(
            "_variable_resolve_result",
            VariableResolveResult(
                resolved_count=resolved_count,
                unresolved_keys=unresolved,
                scope=str(scope),
            ).__dict__,
        )

    def _resolve_actual_scope(self, context: ExecutionContext) -> VariableScope:
        """Resolve actual scope from string (handle 'tenant:current')."""
        if self._scope == "tenant:current":
            tenant_id = getattr(context, "tenant_id", None) or "default"
            return VariableScope.for_tenant(tenant_id)
        return VariableScope.parse(self._scope)

    async def _resolve_in_string(
        self, value: str, resolver: ExpressionResolver, scope: VariableScope
    ) -> str:
        """Resolve ``${var('key', ...)}`` tokens in a string, with scope override."""
        from src.backend.core.dsl.expression_resolver import (
            _VAR_PATTERN,
            _async_sub,
        )

        async def _replace_var(match: re.Match[str]) -> str:
            key = match.group(1)
            scope_str = match.group(2) or str(scope)
            default_quoted = match.group(3) or match.group(4)
            scope_obj = VariableScope.parse(scope_str)
            resolved = await resolver._store.get(key, scope_obj)
            if resolved is None:
                if default_quoted is not None:
                    if default_quoted.startswith(("'", '"')):
                        return default_quoted[1:-1]
                    return default_quoted
                raise ExpressionResolutionError(
                    f"Variable {key!r} not found in scope {scope_str!r}"
                )
            return str(resolved)

        return await _async_sub(_VAR_PATTERN, value, _replace_var)
