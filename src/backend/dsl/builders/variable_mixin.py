"""S127 W2 — VariableMixin for RouteBuilder.

Adds ``.variable(key, default, scope)`` chainable method to
:class:`RouteBuilder` for inline variable resolution.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("VariableMixin",)


class VariableMixin:
    """Mixin: добавляет ``.variable(...)`` chainable method в RouteBuilder.

    Example::

        from src.backend.dsl.builders import RouteBuilder

        builder = (
            RouteBuilder()
            .from_http(path="/api/data")
            .variable("api.timeout", default=30, scope="global")
            .to_response()
        )

    Note: ``.variable(...)`` shortcut delegates to ``.variable_resolve(...)``
    which walks body tree; for full-pipeline scope resolution use
    ``.variable_resolve(scope="...")`` directly.
    """

    __slots__ = ()

    def variable(
        self,
        key: str,
        *,
        default: str | None = None,
        scope: str = "global",
        name: str | None = None,
    ) -> "RouteBuilder":
        """Inline variable resolution shortcut.

        Args:
            key: Variable name (e.g., ``"api.timeout"``).
            default: Default value if not found.
            scope: ``"global"``, ``"tenant:acme"``, ``"route:r1"``,
                ``"tenant:current"`` (use context tenant).
            name: Step name (default: ``f"variable:{key}"``).

        Returns:
            self (chainable).
        """
        return self.variable_resolve(  # type: ignore[attr-defined,return-value]
            scope=scope, fail_on_unresolved=False, name=name or f"variable:{key}"
        )

    def variable_resolve(
        self,
        *,
        scope: str = "global",
        fail_on_unresolved: bool = False,
        name: str | None = None,
    ) -> "RouteBuilder":
        """Resolve all ``${var('key')}`` expressions in exchange.body.

        Args:
            scope: Scope для lookup (default ``"global"``).
            fail_on_unresolved: Error on unresolved (vs log+skip).
            name: Step name.

        Returns:
            self (chainable).
        """
        return self._add_lazy(  # type: ignore[attr-defined,return-value]
            "src.backend.dsl.engine.processors.variable_resolve",
            "VariableResolveProcessor",
            scope=scope,
            fail_on_unresolved=fail_on_unresolved,
            name=name or f"variable_resolve:{scope}",
        )
