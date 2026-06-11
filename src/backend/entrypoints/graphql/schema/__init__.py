from __future__ import annotations

"""GraphQL schema package (S64 W1 decomp from schema.py 492 LOC).

11 Pydantic types + 3 resolvers + 5 helpers decomposed в 5 files:
- ``types.py``: 8 Pydantic types
- ``query.py``: Query resolver (11 methods)
- ``mutation.py``: Mutation resolver (12 methods)
- ``subscription.py``: Subscription resolver (3 methods)
- ``helpers.py``: 5 top-level helper funcs

Backward-compat: ``from src.backend.entrypoints.graphql.schema import Query`` works.
"""


from src.backend.entrypoints.graphql.schema.helpers import (
    _dispatch_action,  # S64 W1: helper re-export
    _dispatch_dsl,  # S64 W1: helper re-export
    _schema_to_order,  # S64 W1: helper re-export
    _schema_to_order_kind,  # S64 W1: helper re-export
    _schema_to_user,  # S64 W1: helper re-export
)
from src.backend.entrypoints.graphql.schema.mutation import (
    Mutation,  # S64 W1: re-export
)
from src.backend.entrypoints.graphql.schema.query import Query  # S64 W1: re-export
from src.backend.entrypoints.graphql.schema.subscription import (
    Subscription,  # S64 W1: re-export
)
from src.backend.entrypoints.graphql.schema.types import (
    ActionResult,  # S64 W1: re-export
    DslResult,  # S64 W1: re-export
    FileType,  # S64 W1: re-export
    OrderKindType,  # S64 W1: re-export
    OrderType,  # S64 W1: re-export
    SystemEventType,  # S64 W1: re-export
    TraceEventType,  # S64 W1: re-export
    UserType,  # S64 W1: re-export
)

__all__ = (
    "OrderKindType",
    "FileType",
    "OrderType",
    "UserType",
    "DslResult",
    "ActionResult",
    "Query",
    "Mutation",
    "TraceEventType",
    "SystemEventType",
    "Subscription",
    "_dispatch_action",
    "_schema_to_order",
    "_schema_to_user",
    "_schema_to_order_kind",
    "_dispatch_dsl",
)
