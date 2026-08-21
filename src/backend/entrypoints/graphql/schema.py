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
