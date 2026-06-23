"""GraphQL DSL result types (S168 W12 P2-4 partial split).

Extracted from src/backend/entrypoints/graphql/schema.py per master
prompt v8 P2-4: "Split by domain: auth_schema.py, workflow_schema.py,
ai_schema.py etc., aggregate in schema.py via strawberry.federation
or simple extend type chains".

Per Ponytail minimum: extract smallest leaf types first (DslResult +
ActionResult — DSL dispatch result types, not domain-specific).
Other types (Query, Mutation, OrderType, UserType, etc.) — separate
WIPs per domain.

Re-export: эти типы импортируются в schema.py через re-import
для backward-compat. Strawberry требует single-schema registration,
поэтому split на отдельные @strawberry.type файлы работает только
если aggregate через strawberry.schema.extend или federation.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.scalars import JSON

__all__ = ("DslResult", "ActionResult", "dispatch_action")


@strawberry.type
class DslResult:
    """Результат выполнения DSL-маршрута."""

    route_id: str
    status: str
    result: JSON | None = None
    error: str | None = None


@strawberry.type
class ActionResult:
    """Результат выполнения action через ActionHandlerRegistry."""

    action: str
    success: bool
    data: JSON | None = None
    error: str | None = None


async def dispatch_action(
    action: str, payload: dict[str, Any] | None = None
) -> ActionResult:
    """S168 W12 P2-4: extracted _dispatch_action → public dispatch_action.

    Диспетчеризует action через общий ``dispatch_action()``.

    IL-CRIT1.5: inline ActionCommandSchema-сборка → ``dispatch_action``
    с ``source="graphql"``. Meta и correlation_id — автоматически.
    """
    from src.backend.entrypoints.base import dispatch_action as _unified_dispatch

    try:
        result = await _unified_dispatch(
            action=action, payload=payload, source="graphql"
        )
        data = result
        if hasattr(result, "model_dump"):
            data = result.model_dump(mode="json")
        elif hasattr(result, "__dict__"):
            data = result.__dict__
        return ActionResult(action=action, success=True, data=data)
    except KeyError:
        return ActionResult(
            action=action, success=False, error=f"Action '{action}' не зарегистрирован"
        )
    except Exception as exc:
        return ActionResult(
            action=action, success=False, error=f"Action '{action}' упал: {exc}"
        )
