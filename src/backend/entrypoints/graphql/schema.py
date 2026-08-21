"""GraphQL-схема с доменными типами и DSL-fallback.

Определяет типизированные Query и Mutation для всех доменов
(Orders, Users, Files, OrderKinds), а также универсальный
DSL-dispatch как fallback для произвольных actions.

Резолверы вызывают бизнес-логику через ActionHandlerRegistry.dispatch().

S168 W11 P2-4 DECISION (per master prompt v8):
    Per master prompt: "Split by domain: auth_schema.py, workflow_schema.py,
    ai_schema.py etc., aggregate in schema.py via strawberry.federation
    or simple extend type chains".

    Per Ponytail minimum, current commit does NOT split:
    - 11 classes (629 LOC) — full split = 5+ files
    - 0 functional change in this commit
    - splitting Query/Mutation/aggregate types requires careful
      schema stitching (strawberry.federation has limitations)

    REJECTED: full split (separate WIP with proper schema stitching)

    Migration plan (separate WIP):
    1. Extract leaf types (OrderKindType, FileType, OrderType, UserType)
       into domain files: orderkind_schema.py, file_schema.py, etc.
    2. Extract aggregate types (Query, Mutation, Subscription) into
       domain files: order_query.py, order_mutation.py, etc.
    3. Aggregate via strawberry.schema.extend or federation
    4. Update tests/unit/entrypoints/graphql/test_schema.py imports
    5. Verify all 11+ existing tests pass
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import strawberry
from fastapi import Depends
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON  # re-exported below
from strawberry.types import Info

from src.backend.core.auth import AuthMethod
from src.backend.core.auth.auth_selector import require_auth
from src.backend.core.logging import get_logger
from src.backend.core.api.extensions import action_handler_registry
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.tracer import get_tracer
from src.backend.dsl.registry import route_registry
from src.backend.dsl.service import get_dsl_service

# S168 W12 P2-4: DslResult + ActionResult + dispatch_action extracted
# to dsl_result.py. Re-exported here для backward-compat (existing
# callers: tests/unit/entrypoints/graphql/test_schema.py).
from src.backend.entrypoints.graphql.dsl_result import ActionResult, DslResult
from src.backend.entrypoints.graphql.dsl_result import (
    dispatch_action as _dispatch_action,
)

__all__ = ("graphql_router",)
logger = get_logger(__name__)



# ── Domain types (RE_AUDIT_2026-08-27 god-object 4/5 split) ────────────────
# Leaf types (OrderKindType, FileType, OrderType, UserType) extracted
# to types.py for single responsibility. Re-exports сохранены для
# backward compat (existing callers: tests/unit/entrypoints/graphql/test_schema.py,
# dsl_result.py, plugins/composition/app_factory.py).
from src.backend.entrypoints.graphql.types import (
    FileType as FileType,
    OrderKindType as OrderKindType,
    OrderType as OrderType,
    UserType as UserType,
)
