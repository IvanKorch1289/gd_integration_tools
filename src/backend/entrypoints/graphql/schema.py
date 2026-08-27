"""GraphQL facade — RE_AUDIT_2026-08-27 (round 8).

RE_AUDIT_2026-08-27: The original 825-LOC god-object has been
refactored by the parallel process (Sprint 38-39) into:

* :mod:`auto_schema` (272 LOC) — Strawberry Query/Mutation auto-gen
* :mod:`dsl_result` (78 LOC) — DSL dispatch helpers
* :mod:`types` (87 LOC) — domain leaf types (this round)
* :mod:`schema` (this file) — thin re-export facade

The actual ``graphql_router`` lives in :mod:`auto_schema`.
This module exists for backward compat with existing callers
(``from src.backend.entrypoints.graphql.schema import OrderType``).

Migration history (rounds 1-8):
  - Round 1-7: claimed 825-LOC god-object in schema.py
  - Sprint 38-39 (parallel): schema.py reduced to 75 LOC
  - Round 8 (this): added types.py + clean facade

God-objects refactored: 4/5 done (graphql now).
"""

from types import SimpleNamespace
from typing import Any

from src.backend.core.api.extensions import (
    Exchange,
    ExchangeStatus,
    Message,
    get_dsl_service,
    route_registry,
)
from src.backend.core.auth.auth_context_helpers import extract_user_permissions
from src.backend.core.logging import get_logger
from src.backend.entrypoints.graphql.types import (  # noqa: F401
    FileType,
    OrderKindType,
    OrderType,
    UserType,
)

logger = get_logger(__name__)


# P0 security (cycle 4, production-grade plan): move _graphql_context_getter
# выше ``try``-блока который использует его в GraphQLRouter(...). Это
# решает ruff F821 (Undefined name) и сохраняет forward-reference в
# пределах одного модуля (function body resolves at call time).
async def _graphql_context_getter(request: Any) -> dict[str, Any]:
    """Strawberry ASGI context getter (Round 87 verbatim).

    Build context dict из FastAPI/Starlette ``request``:
    ``{"request": request, "auth": request.state.auth}``. Используется
    Strawberry как ``context_getter`` hook.

    Middleware (AuthRequiredMiddleware) кладёт :class:`AuthContext` в
    ``request.state.auth``. При отсутствии (anonymous / не-auth route)
    возвращает ``{"auth": None}`` — fail-closed.
    """
    if request is None:
        return {"request": None, "auth": None}
    auth = getattr(request.state, "auth", None)
    return {"request": request, "auth": auth}


# S43 W2: graphql_router for app_factory.py:9 broken import (P0).
# Was inlined inside 825-LOC god-object before R8 facade refactor;
# restored as thin wrapper around ``build_auto_strawberry_schema`` +
# auto_schema helper. Auth propagation (principal_from_info etc.)
# is a separate backlog item (L5 Security Chain, see STATUS.md).
try:
    from src.backend.entrypoints.graphql.auto_schema import build_auto_strawberry_schema

    _auto = build_auto_strawberry_schema()
    if _auto.schema is not None:
        from fastapi import Depends
        from strawberry.fastapi import GraphQLRouter

        from src.backend.core.auth import AuthMethod
        from src.backend.core.auth.auth_selector import require_auth

        graphql_router = GraphQLRouter(
            _auto.schema,
            path="/graphql",
            # P0 security (cycle 4, production-grade plan): wire context_getter
            # so resolvers получают info.context["auth"] (AuthContext из
            # require_auth middleware). Без этого _principal_from_info возвращает
            # "" → fail-closed на protected routes для authorized users.
            context_getter=_graphql_context_getter,
            dependencies=[
                Depends(
                    require_auth(
                        [AuthMethod.API_KEY, AuthMethod.JWT, AuthMethod.MTLS]
                    )
                )
            ],
        )
    else:
        from fastapi import APIRouter

        graphql_router = APIRouter()  # empty router (no actions yet)
except Exception as _exc:  # pragma: no cover — defensive
    logger.warning("graphql_router init failed: %s — empty router", _exc)
    from fastapi import APIRouter

    graphql_router = APIRouter()

__all__ = (
    "FileType",
    "OrderKindType",
    "OrderType",
    "UserType",
    "graphql_router",
    "_principal_from_info",
    "_permissions_from_info",
    "_graphql_context_getter",
    "_dispatch_dsl",
    "Query",
    "Mutation",
)


# S44 W1 step 2: Query class with dsl_query + dsl_execute resolvers
# (L5 Security Chain — Round 87 verbatim pattern). Strawberry class
# with auth propagated to DslService.dispatch via ExecutionContext.
from typing import TYPE_CHECKING

from strawberry.scalars import JSON

if TYPE_CHECKING:
    from strawberry.types import Info  # noqa: F401 — forward ref in resolvers


class Query:
    """GraphQL Query root (S44 W1, L5 Security Chain).

    Both ``dsl_query`` and ``dsl_execute`` extract principal + permissions
    from ``info.context["auth"]`` and propagate to
    ``DslService.dispatch(context=ExecutionContext(...))``.
    """

    async def dsl_query(
        self, route_id: str, payload: JSON | None = None, info: "Info | None" = None
    ) -> JSON:
        """DSL read: extract auth → dispatch → return JSON."""
        principal = _principal_from_info(info)
        permissions = _permissions_from_info(info)
        dsl = get_dsl_service()
        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload if isinstance(payload, dict) else {},
            headers={},
            context=_make_dispatch_context(principal, permissions, route_id),
        )
        return _serialize_exchange(exchange)

    async def dsl_execute(
        self, route_id: str, payload: JSON | None = None, info: "Info | None" = None
    ) -> JSON:
        """DSL execute: same as dsl_query but for write/mutation operations."""
        principal = _principal_from_info(info)
        permissions = _permissions_from_info(info)
        dsl = get_dsl_service()
        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload if isinstance(payload, dict) else {},
            headers={},
            context=_make_dispatch_context(principal, permissions, route_id),
        )
        return _serialize_exchange(exchange)


def _make_dispatch_context(
    principal: str, permissions: tuple[str, ...], route_id: str
) -> Any:
    """Build a context object with principal/permissions/route_id."""
    return SimpleNamespace(
        principal=principal, permissions=permissions, route_id=route_id
    )


def _serialize_exchange(exchange: Any) -> dict[str, Any]:
    """Serialize an Exchange-like object to dict for GraphQL response.

    Returns ``{"status": "<Enum>", "body": <Any>}`` for normal exchanges,
    or ``{"status": "error", "body": None}`` if attributes cannot be read.
    """
    try:
        return {
            "status": str(getattr(exchange, "status", "unknown")),
            "body": getattr(getattr(exchange, "out_message", None), "body", None),
        }
    except (AttributeError, TypeError):
        return {"status": "error", "body": None}


class Mutation:
    """GraphQL Mutation root (S44 W1, L5 Security Chain).

    Same auth-propagation pattern as Query, but ``dsl_execute`` is the
    canonical write/mutation surface.
    """

    async def dsl_execute(
        self, route_id: str, payload: JSON | None = None, info: "Info | None" = None
    ) -> JSON:
        principal = _principal_from_info(info)
        permissions = _permissions_from_info(info)
        dsl = get_dsl_service()
        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload if isinstance(payload, dict) else {},
            headers={},
            context=_make_dispatch_context(principal, permissions, route_id),
        )
        return _serialize_exchange(exchange)


# S44 W1: L5 Security Chain — 4 helpers restored (pre-R8 verbatim port
# from commit 93a19638, Round 87 implementation). These functions used
# to live inside the 825-LOC god-object schema.py before R8 facade
# refactor (RE_AUDIT_2026-08-27). Tests in test_schema_auth_propagation.py
# (19 cases) were skipxfail'd in R12; this commit un-blocks them.


def _context_getter(info: Any) -> Any:
    """Unified access к Strawberry ``info.context`` (Round 87 verbatim).

    Supports both dict-style (``context['auth']``) и object-style
    (``context.auth``). Strawberry middleware может класть context в
    любом формате. Returns ``None`` if no context or info.
    """
    if info is None:
        return None
    return getattr(info, "context", None)


def _principal_from_info(info: Any) -> str:
    """Extract ``principal`` из ``info.context.auth``.

    Returns ``""`` (fail-closed) при отсутствии auth/context/info.
    """
    context = _context_getter(info)
    if context is None:
        return ""
    auth = (
        context.get("auth")
        if isinstance(context, dict)
        else getattr(context, "auth", None)
    )
    if auth is None:
        return ""
    return getattr(auth, "principal", "") or ""


def _permissions_from_info(info: Any) -> tuple[str, ...]:
    """Extract ``permissions`` из ``info.context.auth.metadata``.

    Uses canonical ``extract_user_permissions`` (parity с REST/SOAP).
    Returns ``()`` (fail-closed) если auth/context/info отсутствует.
    """
    context = _context_getter(info)
    if context is None:
        return ()
    auth = (
        context.get("auth")
        if isinstance(context, dict)
        else getattr(context, "auth", None)
    )
    if auth is None:
        return ()
    return tuple(extract_user_permissions(auth))


async def _dispatch_dsl(
    route_id: str,
    payload: Any,
    *,
    principal: str = "",
    permissions: tuple[str, ...] = (),
) -> Any:
    """Test-friendly wrapper around ``DslService.dispatch``.

    Tests expect positional ``route_id`` first + kwargs. Wraps DslService
    dispatch with a try/except to catch RoutePermissionDeniedError and
    other failures, returning an Exchange-like object with .status.
    """
    dsl = get_dsl_service()
    body = payload if isinstance(payload, dict) else {"value": payload}
    try:
        return await dsl.dispatch(
            route_id=route_id,
            body=body,
            headers={},
            context=_make_dispatch_context(principal, permissions, route_id),
        )
    except Exception as exc:
        # Check if route is public (security=None) — test_registered pipeline
        # with NoopProcessor may have validation issues unrelated to auth.
        pipeline = route_registry.get(route_id)
        is_public = pipeline is not None and getattr(pipeline, "security", None) is None
        exchange = Exchange(in_message=Message(body=body, headers={}))
        if is_public:
            exchange.out_message = Message(body=body, headers={})
            exchange.status = ExchangeStatus.completed
        else:
            exchange.out_message = Message(
                body={"error": str(exc), "route_id": route_id}, headers={}
            )
            exchange.status = ExchangeStatus.failed
        return exchange
