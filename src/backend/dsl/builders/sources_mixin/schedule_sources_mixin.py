from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

class ScheduleSourcesMixin:
    """schedule-based source registration для RouteBuilder. S57 W2 extraction."""

    __slots__ = ()

    @classmethod
    def from_schedule(
        cls, route_id: str, cron_expr: str, **kwargs: Any
    ) -> RouteBuilder:
        """Создаёт маршрут с источником cron-расписания.

        Лениво импортирует :class:`PollingSource` из
        ``infrastructure.sources.polling`` для cron-based опроса.
        Для полноценного cron — интеграция с APScheduler через
        ``infrastructure.scheduler.scheduled_tasks``.

        Args:
            route_id: Уникальный ID маршрута.
            cron_expr: Cron-выражение (``* * * * *`` style, 5 полей).
            **kwargs: Дополнительные параметры: ``url`` (polling URL),
                ``interval_seconds`` и др.

        Returns:
            RouteBuilder с ``source`` установленным в ``schedule:<cron_expr>``.

        Example::

            route = (
                RouteBuilder.from_schedule(
                    "reports.daily",
                    cron_expr="0 9 * * 1-5",
                )
                .dispatch_action("reports.generate_daily")
                .build()
            )
        """
        builder: RouteBuilder = cls(route_id=route_id, source=f"schedule:{cron_expr}")
        # Сохраняем cron и kwargs для последующей регистрации в APScheduler
        object.__setattr__(
            builder,
            "_source_config",
            {"type": "schedule", "cron_expr": cron_expr, **kwargs},
        )
        return builder

