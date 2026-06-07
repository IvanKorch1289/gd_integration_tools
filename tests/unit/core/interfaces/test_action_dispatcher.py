"""Unit tests for :class:`ActionDispatcher` / :class:`ActionGatewayDispatcher` Protocols.

W14.1 + W14.1.A (Phase A) — covers:

* DTOs: :class:`ActionError`, :class:`ActionResult`, :class:`DispatchContext`,
  :class:`ActionMetadata`.
* Protocols (legacy + Gateway): ``dispatch`` / ``is_registered`` / ``list_actions``
  / ``get_metadata`` / ``list_metadata`` / ``register_middleware``.
* Middleware chain (``ActionMiddleware`` ``__call__`` signature).
* Type aliases (``TransportName``, ``SideEffect``).
* Backward-compat: legacy ``ActionDispatcher.dispatch(ActionCommandSchema)``
  is still importable and Protocol-conformant.

Reference implementation: ``src/backend/core/interfaces/action_dispatcher.py``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pytest

from src.backend.core.interfaces.action_dispatcher import (
    ActionDispatcher,
    ActionError,
    ActionGatewayDispatcher,
    ActionMetadata,
    ActionMiddleware,
    ActionResult,
    DispatchContext,
    MiddlewareNextHandler,
    SideEffect,
    TransportName,
    _seq_to_tuple,
)
from src.backend.core.types.invocation_command import (
    ActionCommandMetaSchema,
    ActionCommandSchema,
)

# ----------------------------------------------------------------------
# Fakes / helpers
# ----------------------------------------------------------------------


class _FakeLegacyDispatcher:
    """Minimal implementation of the legacy :class:`ActionDispatcher` Protocol."""

    def __init__(self) -> None:
        self._registered: tuple[str, ...] = ("orders.create", "orders.get")

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        return {"echo": command.action, "payload": command.payload}

    def is_registered(self, action: str) -> bool:
        return action in self._registered

    def list_actions(self) -> tuple[str, ...]:
        return self._registered


class _FakeGatewayDispatcher:
    """Full implementation of the extended :class:`ActionGatewayDispatcher`."""

    def __init__(self) -> None:
        self._middlewares: list[ActionMiddleware] = []
        self._actions: dict[str, ActionMetadata] = {
            "orders.create": ActionMetadata(
                action="orders.create",
                description="Create an order",
                transports=("http", "grpc"),
                side_effect="write",
                idempotent=True,
                permissions=("orders:write",),
                rate_limit=100,
                timeout_ms=5000,
                error_types=("validation.failed", "conflict"),
                tags=("orders", "public"),
            ),
            "orders.get": ActionMetadata(
                action="orders.get",
                description="Fetch an order",
                transports=("http",),
                side_effect="read",
            ),
        }

    async def dispatch(
        self, action: str, payload: Mapping[str, Any], context: DispatchContext
    ) -> ActionResult:
        # Naive "routing": pass through middlewares in order, then succeed.
        if not self._actions:
            return ActionResult(
                success=False,
                error=ActionError(code="action.not_found", message=action),
            )
        return ActionResult(success=True, data={"action": action})

    def get_metadata(self, action: str) -> ActionMetadata | None:
        return self._actions.get(action)

    def list_actions(self, transport: TransportName | None = None) -> tuple[str, ...]:
        if transport is None:
            return tuple(sorted(self._actions))
        return tuple(
            sorted(
                name for name, md in self._actions.items() if transport in md.transports
            )
        )

    def list_metadata(
        self, transport: TransportName | None = None
    ) -> tuple[ActionMetadata, ...]:
        if transport is None:
            return tuple(self._actions[a] for a in sorted(self._actions))
        return tuple(
            md
            for name in sorted(self._actions)
            if transport in (md := self._actions[name]).transports
        )

    def register_middleware(self, middleware: ActionMiddleware) -> None:
        self._middlewares.append(middleware)


class _LoggingMiddleware:
    """A trivial middleware — records calls and delegates to next."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    async def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        next_handler: MiddlewareNextHandler,
    ) -> ActionResult:
        self.calls.append(action)
        return await next_handler(action, payload, context)


class _IncompleteDispatcher:
    """Missing ``is_registered`` / ``list_actions`` — must fail isinstance."""

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        return None


# ----------------------------------------------------------------------
# Import / module surface
# ----------------------------------------------------------------------


def test_dispatcher_imports() -> None:
    """All public names from the module are importable."""
    from src.backend.core.interfaces import action_dispatcher as mod

    assert mod.ActionDispatcher is not None
    assert mod.ActionGatewayDispatcher is not None
    assert mod.ActionResult is not None
    assert mod.ActionError is not None
    assert mod.DispatchContext is not None
    assert mod.ActionMetadata is not None
    assert mod.ActionMiddleware is not None


def test_dunder_all_exports() -> None:
    """``__all__`` lists exactly the documented public surface."""
    from src.backend.core.interfaces import action_dispatcher as mod

    assert set(mod.__all__) == {
        "ActionDispatcher",
        "ActionError",
        "ActionGatewayDispatcher",
        "ActionMetadata",
        "ActionMiddleware",
        "ActionResult",
        "DispatchContext",
        "MiddlewareNextHandler",
        "SideEffect",
        "TransportName",
    }


# ----------------------------------------------------------------------
# DTO construction
# ----------------------------------------------------------------------


def test_action_error_creation() -> None:
    """``ActionError`` carries code/message/details/recoverable."""
    err = ActionError(
        code="validation.failed",
        message="bad input",
        details={"field": "name"},
        recoverable=True,
    )
    assert err.code == "validation.failed"
    assert err.message == "bad input"
    assert err.details == {"field": "name"}
    assert err.recoverable is True


def test_action_error_defaults() -> None:
    """``ActionError`` defaults: details=None, recoverable=False."""
    err = ActionError(code="oops", message="x")
    assert err.details is None
    assert err.recoverable is False


def test_action_result_success_envelope() -> None:
    """``ActionResult`` on success: data populated, error=None, default metadata."""
    result = ActionResult(success=True, data={"order_id": 1})
    assert result.success is True
    assert result.data == {"order_id": 1}
    assert result.error is None
    assert result.metadata == {}


def test_action_result_failure_envelope() -> None:
    """``ActionResult`` on failure: success=False, error populated."""
    err = ActionError(code="not_found", message="missing")
    result = ActionResult(success=False, error=err)
    assert result.success is False
    assert result.data is None
    assert result.error is err


def test_dispatch_context_defaults() -> None:
    """``DispatchContext`` defaults: source='internal', no IDs, no attributes."""
    ctx = DispatchContext()
    assert ctx.correlation_id is None
    assert ctx.tenant_id is None
    assert ctx.user_id is None
    assert ctx.idempotency_key is None
    assert ctx.source == "internal"
    assert ctx.trace_parent is None
    assert ctx.attributes == {}


def test_dispatch_context_with_idempotency() -> None:
    """``DispatchContext`` propagates the idempotency_key verbatim."""
    ctx = DispatchContext(
        correlation_id="corr-1",
        tenant_id="acme",
        user_id="u-7",
        idempotency_key="idem-xyz-123",
        source="http",
        trace_parent="00-trace-span-01",
    )
    assert ctx.correlation_id == "corr-1"
    assert ctx.tenant_id == "acme"
    assert ctx.user_id == "u-7"
    assert ctx.idempotency_key == "idem-xyz-123"
    assert ctx.source == "http"
    assert ctx.trace_parent == "00-trace-span-01"


# ----------------------------------------------------------------------
# Protocol conformance
# ----------------------------------------------------------------------


def test_action_dispatcher_protocol_is_runtime_checkable() -> None:
    """Legacy ``ActionDispatcher`` accepts a complete fake via ``isinstance``."""
    assert isinstance(_FakeLegacyDispatcher(), ActionDispatcher)


def test_action_dispatcher_rejects_incomplete() -> None:
    """Incomplete dispatcher (missing 2/3 methods) does not satisfy Protocol."""
    assert not isinstance(_IncompleteDispatcher(), ActionDispatcher)


def test_gateway_dispatcher_protocol_is_runtime_checkable() -> None:
    """Extended ``ActionGatewayDispatcher`` accepts a complete fake via ``isinstance``."""
    assert isinstance(_FakeGatewayDispatcher(), ActionGatewayDispatcher)


def test_abc_protocols_cannot_instantiate() -> None:
    """Protocols themselves are not instantiable (no constructor state)."""
    with pytest.raises((TypeError, Exception)):
        # Protocols raise on direct instantiation; we accept any exception class
        # because the actual message varies across Python versions.
        ActionDispatcher()  # type: ignore[call-arg]


def test_concrete_implementation_required() -> None:
    """A subclass providing no methods fails isinstance for the Protocol."""

    class _Empty:
        pass

    assert not isinstance(_Empty(), ActionDispatcher)
    assert not isinstance(_Empty(), ActionGatewayDispatcher)


# ----------------------------------------------------------------------
# Behavioural round-trip
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_dispatch_returns_echo() -> None:
    """Legacy ``dispatch(ActionCommandSchema)`` echoes action + payload."""
    dispatcher = _FakeLegacyDispatcher()
    cmd = ActionCommandSchema(
        action="orders.create",
        payload={"sku": "ABC"},
        meta=ActionCommandMetaSchema(source="http"),
    )
    result = await dispatcher.dispatch(cmd)
    assert result == {"echo": "orders.create", "payload": {"sku": "ABC"}}


def test_legacy_list_actions_sorted() -> None:
    """Legacy ``list_actions`` returns a sorted tuple of registered names."""
    dispatcher = _FakeLegacyDispatcher()
    actions = dispatcher.list_actions()
    assert actions == ("orders.create", "orders.get")
    assert actions == tuple(sorted(actions))


def test_legacy_is_registered_lookup() -> None:
    """``is_registered`` answers True/False based on the registry contents."""
    dispatcher = _FakeLegacyDispatcher()
    assert dispatcher.is_registered("orders.create") is True
    assert dispatcher.is_registered("orders.delete") is False


@pytest.mark.asyncio
async def test_gateway_dispatch_returns_envelope() -> None:
    """Gateway ``dispatch`` returns a successful ``ActionResult`` envelope."""
    dispatcher = _FakeGatewayDispatcher()
    ctx = DispatchContext(tenant_id="acme", source="http")
    result = await dispatcher.dispatch(
        action="orders.create", payload={"sku": "ABC"}, context=ctx
    )
    assert isinstance(result, ActionResult)
    assert result.success is True
    assert result.data == {"action": "orders.create"}


def test_gateway_list_actions_filtered_by_transport() -> None:
    """``list_actions(transport='http')`` includes only actions with that transport."""
    dispatcher = _FakeGatewayDispatcher()
    assert dispatcher.list_actions(transport="http") == ("orders.create", "orders.get")
    assert dispatcher.list_actions(transport="grpc") == ("orders.create",)
    # 'queue' is supported by neither action
    assert dispatcher.list_actions(transport="queue") == ()


def test_gateway_get_metadata_contract() -> None:
    """``get_metadata`` returns ``ActionMetadata`` for known, ``None`` for unknown."""
    dispatcher = _FakeGatewayDispatcher()
    md = dispatcher.get_metadata("orders.create")
    assert isinstance(md, ActionMetadata)
    assert md.action == "orders.create"
    assert md.side_effect == "write"
    assert md.idempotent is True
    assert md.transports == ("http", "grpc")
    assert dispatcher.get_metadata("orders.delete") is None


def test_gateway_register_middleware_appends() -> None:
    """``register_middleware`` appends to the internal chain in order."""
    dispatcher = _FakeGatewayDispatcher()
    mw1 = _LoggingMiddleware()
    mw2 = _LoggingMiddleware()
    dispatcher.register_middleware(mw1)
    dispatcher.register_middleware(mw2)
    assert dispatcher._middlewares == [mw1, mw2]


# ----------------------------------------------------------------------
# Middleware behaviour
# ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_middleware_chainable() -> None:
    """A middleware can delegate to ``next_handler`` and forward the result."""
    mw = _LoggingMiddleware()
    seen: list[str] = []

    async def _next(
        action: str, payload: Mapping[str, Any], context: DispatchContext
    ) -> ActionResult:
        seen.append(f"next:{action}")
        return ActionResult(success=True, data={"chained": True})

    result = await mw(
        action="orders.create",
        payload={},
        context=DispatchContext(tenant_id="acme"),
        next_handler=_next,
    )
    assert result.success is True
    assert result.data == {"chained": True}
    assert mw.calls == ["orders.create"]
    assert seen == ["next:orders.create"]


# ----------------------------------------------------------------------
# Type-alias / helper checks
# ----------------------------------------------------------------------


def test_transport_name_is_str_alias() -> None:
    """``TransportName`` is documented as a free-form string (extensibility)."""
    assert TransportName("http") == "http"
    assert TransportName("custom-thing") == "custom-thing"


def test_side_effect_is_str_alias() -> None:
    """``SideEffect`` is a free-form string; default is ``"none"``."""
    assert SideEffect("read") == "read"
    assert SideEffect("external") == "external"
    # Default value of ``ActionMetadata.side_effect`` must be ``"none"``.
    md = ActionMetadata(action="noop")
    assert md.side_effect == "none"


def test_seq_to_tuple_helper() -> None:
    """``_seq_to_tuple`` converts a ``Sequence`` to a tuple; ``None`` → empty."""
    assert _seq_to_tuple(None) == ()
    assert _seq_to_tuple(["a", "b", "c"]) == ("a", "b", "c")
    assert _seq_to_tuple(("x",)) == ("x",)
    # Resulting type is always ``tuple`` (slot-friendly).
    assert isinstance(_seq_to_tuple(["a"]), tuple)
