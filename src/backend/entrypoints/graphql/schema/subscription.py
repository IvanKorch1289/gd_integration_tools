from __future__ import annotations
"""S64 W1 — subscription.py part of graphql schema decomp.

Subscription resolver (3 methods).
"""

from collections.abc import AsyncGenerator
from datetime import datetime
from typing import Any

import strawberry
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from src.backend.core.logging import get_logger
from src.backend.dsl.service import get_dsl_service
from src.backend.entrypoints.graphql.schema.types import (
    TraceEventType,
    SystemEventType,
)  # S64 W1: types




@strawberry.type


class Subscription:
    """GraphQL Subscriptions — real-time события."""

    @strawberry.subscription(
        description="Трассировка выполнения маршрута в реальном времени."
    )
    async def route_trace(
        self, route_id: str, info: Info
    ) -> AsyncGenerator[TraceEventType]:
        """Выполнить операцию route trace."""
        from src.backend.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        async for event in tracer.subscribe(route_id):
            yield TraceEventType(
                route_id=event.route_id,
                processor_name=event.processor_name,
                processor_type=event.processor_type,
                phase=event.phase,
                duration_ms=event.duration_ms,
                timestamp=event.timestamp,
                error=event.error,
            )

    @strawberry.subscription(description="Все trace-события (для dashboard).")
    async def all_traces(self, info: Info) -> AsyncGenerator[TraceEventType]:
        """Выполнить операцию all traces."""
        from src.backend.dsl.engine.tracer import get_tracer

        tracer = get_tracer()
        async for event in tracer.subscribe_all():
            yield TraceEventType(
                route_id=event.route_id,
                processor_name=event.processor_name,
                processor_type=event.processor_type,
                phase=event.phase,
                duration_ms=event.duration_ms,
                timestamp=event.timestamp,
                error=event.error,
            )

    @strawberry.subscription(
        description="Системные события (health check каждые 30 сек)."
    )
    async def system_health(self, info: Info) -> AsyncGenerator[SystemEventType]:
        """Выполнить операцию system health."""
        import asyncio
        from datetime import UTC, datetime

        while True:
            try:
                from src.backend.core.di.providers import (
                    get_healthcheck_session_provider,
                )

                hc_factory = get_healthcheck_session_provider()
                async with hc_factory() as hc:
                    result = await hc.check_all_services()
                yield SystemEventType(
                    event_type="health_check",
                    data=result,
                    timestamp=datetime.now(UTC).isoformat(),
                )
            except Exception as exc:
                yield SystemEventType(
                    event_type="health_check_error",
                    data={"error": str(exc)},
                    timestamp=datetime.now(UTC).isoformat(),
                )
            await asyncio.sleep(30)



