"""Unified OTel semantic model — correlation + business context (Wave 1 P0 #52).

Проблема (EP-R1):
    Метрики и трейсы разных протоколов несопоставимы:
    - HTTP-трейс и MQ-трейс не связаны.
    - DB-query не привязан к бизнес-операции.
    - "Где моя заявка?" — нет способа найти все события по business key.

Решение:
    ``SemanticContext`` + ``CorrelationPropagator``:

    1. ``SemanticContext`` — единый набор атрибутов:
       - ``trace_id`` / ``span_id`` — W3C Trace Context.
       - ``correlation_id`` — request-level correlation.
       - ``business_keys`` — dict {order_id, file_id, customer_id, ...}.
       - ``tenant_id`` — multi-tenancy.
       - ``route_id`` — для route execution.
       - ``user_id`` / ``session_id`` — для actor.

    2. ``CorrelationPropagator`` — extract/inject для cross-system:
       - ``inject_context(context)`` → dict (headers + body metadata).
       - ``extract_context(headers)`` → SemanticContext.

    3. ``set_current_context(context)`` — async-safe via contextvars.

Использование::

    from src.backend.core.observability_v2 import (
        SemanticContext, get_current_context, set_current_context,
    )

    ctx = SemanticContext(
        correlation_id="trace-abc",
        business_keys={"order_id": "o1"},
        tenant_id="tenant-1",
    )
    set_current_context(ctx)

    # В любом месте:
    current = get_current_context()
    assert current.business_keys["order_id"] == "o1"
"""

from __future__ import annotations

from src.backend.core.observability_v2.context import (
    SemanticContext,
    get_current_context,
    reset_current_context,
    set_current_context,
)
from src.backend.core.observability_v2.propagator import (
    CorrelationPropagator,
    TraceContextCarrier,
)

__all__ = (
    "CorrelationPropagator",
    "SemanticContext",
    "TraceContextCarrier",
    "get_current_context",
    "reset_current_context",
    "set_current_context",
)
