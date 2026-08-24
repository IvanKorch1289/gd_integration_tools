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

from src.backend.core.logging import get_logger
from src.backend.entrypoints.graphql.types import (  # noqa: F401
    FileType,
    OrderKindType,
    OrderType,
    UserType,
)

logger = get_logger(__name__)


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
)
