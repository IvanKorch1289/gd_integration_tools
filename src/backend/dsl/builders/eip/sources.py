"""Source EIP-методы: from_interval / from_webhook / from_file / from_sql /
from_http / from_s3 / sse_source.

Sprint 60 W4 — split из eip.py (1354 LOC).

Cycle 46: lazy task creation. The 4 sensor-based source methods
(from_file, from_sql, from_http, from_s3) previously called
asyncio.create_task() at DSL build time — which fails outside a
running event loop. Fix: defer task creation to when a loop is
available. The :class:`FileSensorTaskWrapper` accepts a
task_factory callback that's invoked lazily.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.dsl.builders.eip._base import EIPMixinBase

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("SourcesEIPsMixin",)


def _create_or_defer_sensor_task(
    coro_factory: Callable[[], Any],
    *,
    name: str,
) -> Any:
    """Cycle 46: create asyncio.Task if event loop is running, else defer.

    Returns either:
    - The created :class:`asyncio.Task` (if event loop was running)
    - A lazy-task descriptor (callable returning Task when invoked)

    The lazy-task descriptor is invoked by FileSensorTaskWrapper.start()
    when called from an async context. This allows DSL to be built in
    sync contexts (no event loop) without raising RuntimeError.

    Args:
        coro_factory: Callable returning the coroutine to wrap in a Task.
            Called once (eagerly or lazily) when the task is started.
        name: Task name (used for debugging).

    Returns:
        Either asyncio.Task or a deferred-task descriptor with a
        ``.start()`` method that creates the actual task on demand.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop is not None:
        # Eager path: create task immediately.
        return asyncio.create_task(coro_factory(), name=name)

    # Lazy path: return descriptor that defers task creation.
    class _DeferredTask:
        """Defers asyncio.Task creation until start() is called from async context."""

        def __init__(self) -> None:
            self._task: asyncio.Task | None = None

        def start(self) -> asyncio.Task:
            if self._task is not None:
                return self._task
            self._task = asyncio.create_task(coro_factory(), name=name)
            return self._task

        async def stop(self) -> None:
            if self._task and not self._task.done():
                self._task.cancel()
                try:
                    await self._task
                except (asyncio.CancelledError, Exception):
                    pass

    return _DeferredTask()


class SourcesEIPsMixin(EIPMixinBase):
    """Camel-style ``from(...)`` EIP methods + SSE source."""

    def from_interval(
        self,
        interval_s: float,
        *,
        start_immediately: bool = False,
        payload: dict[str, Any] | None = None,
    ) -> RouteBuilder:
        """Camel-style ``from(\"timer:foo?period=...\")`` — periodic trigger.

        Регистрирует IntervalTrigger в TriggerRegistry, который каждые
        ``interval_s`` секунд запускает route. При register() / startup
        приложения trigger.start() вызывается автоматически.

        Args:
            interval_s: interval в секундах.
            start_immediately: запустить сразу (default — после первого interval).
            payload: static dict для payload.
        """
        from src.backend.dsl.orchestration.triggers import (
            IntervalTrigger,
            get_trigger_registry,
        )

        trigger = IntervalTrigger(
            name=f"interval_{id(self)}",
            route_id=getattr(self, "route_id", "") or "_pending_route_",
            interval_s=interval_s,
            start_immediately=start_immediately,
            payload=payload,
        )
        get_trigger_registry().register(trigger)
        return self  # type: ignore

    def from_cron(
        self,
        cron_expr: str,
        *,
        timezone_name: str = "UTC",
        payload: dict[str, Any] | None = None,
    ) -> RouteBuilder:
        """Camel-style ``from(\"cron:*/5 * * * *\")`` — cron periodic trigger (S168 W10 P1-2).

        Real periodic dispatch (loop until stop) per ``cron_expr``.
        Отличие от ``RouteBuilder.schedule(cron=...)`` (который defers
        single execution): ``from_cron`` запускает route каждый cron tick
        бесконечно (до stop trigger'а или shutdown приложения).

        Args:
            cron_expr: 5-field cron expression (e.g. ``"*/5 * * * *"``).
            timezone_name: IANA timezone (default UTC).
            payload: static dict для payload.

        Example::

            builder.from_cron("*/5 * * * *", timezone_name="Europe/Moscow")
        """
        from src.backend.dsl.orchestration.triggers import (
            CronTrigger,
            get_trigger_registry,
        )

        trigger = CronTrigger(
            name=f"cron_{id(self)}",
            route_id=getattr(self, "route_id", "") or "_pending_route_",
            cron_expr=cron_expr,
            timezone_name=timezone_name,
            payload=payload,
        )
        get_trigger_registry().register(trigger)
        return self  # type: ignore

    def from_webhook(self, path: str, *, method: str = "POST") -> RouteBuilder:
        """Camel-style ``from(\"http:host/path\")`` — HTTP webhook trigger.

        Регистрирует FastAPI route на ``path``. При вызове (любой JSON body)
        → dsl_service.dispatch(route_id, body, headers).
        """
        from src.backend.dsl.orchestration.triggers import (
            WebhookTrigger,
            get_trigger_registry,
        )

        trigger = WebhookTrigger(
            name=f"webhook_{path.replace('/', '_').strip('_') or 'root'}",
            route_id=getattr(self, "route_id", "") or "_pending_route_",
            path=path,
            method=method,
        )
        get_trigger_registry().register(trigger)
        return self  # type: ignore

    def from_file(
        self,
        path: str,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        poll_interval_s: float = 1.0,
    ) -> RouteBuilder:
        """Camel-style ``from(\"file:directory?pattern=*\")`` — file sensor trigger.

        Apache Airflow FileSensor analogue. При появлении/изменении файла
        (matching pattern) → dsl_service.dispatch(route_id, {}, headers).
        """
        from src.backend.core.orchestration.airflow_sensors import FileSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = FileSensor(
            path=path,
            pattern=pattern,
            recursive=recursive,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"file_{path.replace('/', '_').strip('_')}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "route_id", "") or "_pending_route_"
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default",
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "file", "x-sensor-path": path},
                    )
                await asyncio.sleep(poll_interval_s)

        task = _create_or_defer_sensor_task(_runner, name=f"sensor:file:{path}")
        # _DeferredTask has .start() method; eager asyncio.Task does not.
        if hasattr(task, "start"):
            get_trigger_registry().register(_FileSensorWrapper(
                task_factory=lambda: task.start(),
                name=f"sensor:file:{path}",
            ))
        else:
            get_trigger_registry().register(_FileSensorWrapper(task=task, name=f"sensor:file:{path}"))
        return self  # type: ignore

    def from_sql(
        self,
        dsn: str,
        query: str,
        *,
        predicate: str | None = None,
        poll_interval_s: float = 5.0,
    ) -> RouteBuilder:
        """Camel-style ``from(\"sql:...\")`` — SQL sensor trigger.

        Apache Airflow SqlSensor analogue. Polls query до match (any row
        или JMESPath predicate). При match → dsl_service.dispatch.
        """
        from src.backend.core.orchestration.airflow_sensors import SqlSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = SqlSensor(
            dsn=dsn, query=query, predicate=predicate, poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"sql_{id(self)}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "route_id", "") or "_pending_route_"
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default",
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "sql", "x-sensor-dsn": dsn.split("@")[-1]},
                    )
                await asyncio.sleep(poll_interval_s)

        task = _create_or_defer_sensor_task(_runner, name=f"sensor:sql:{id(self)}")
        if hasattr(task, "start"):  # _DeferredTask
            get_trigger_registry().register(_FileSensorWrapper(
                task_factory=lambda: task.start(), name=f"sensor:sql:{id(self)}",
            ))
        else:
            get_trigger_registry().register(_FileSensorWrapper(task=task, name=f"sensor:sql:{id(self)}"))
        return self  # type: ignore

    def from_http(
        self,
        url: str,
        *,
        expected_status: int = 200,
        method: str = "GET",
        body_match: str | None = None,
        poll_interval_s: float = 10.0,
    ) -> RouteBuilder:
        """Camel-style ``from(\"http:url\")`` — HTTP sensor trigger.

        Apache Airflow HttpSensor analogue. Polls endpoint до match.
        При match → dsl_service.dispatch.
        """
        from src.backend.core.orchestration.airflow_sensors import HttpSensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = HttpSensor(
            url=url,
            expected_status=expected_status,
            method=method,
            body_match=body_match,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"http_{id(self)}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "route_id", "") or "_pending_route_"
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default",
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={"x-sensor": "http", "x-sensor-url": url},
                    )
                await asyncio.sleep(poll_interval_s)

        task = _create_or_defer_sensor_task(_runner, name=f"sensor:http:{url}")
        if hasattr(task, "start"):  # _DeferredTask
            get_trigger_registry().register(_FileSensorWrapper(
                task_factory=lambda: task.start(), name=f"sensor:http:{url}",
            ))
        else:
            get_trigger_registry().register(_FileSensorWrapper(task=task, name=f"sensor:http:{url}"))
        return self  # type: ignore

    def from_s3(
        self,
        bucket: str,
        key: str,
        *,
        region: str = "us-east-1",
        endpoint_url: str | None = None,
        poll_interval_s: float = 30.0,
    ) -> RouteBuilder:
        """Camel-style ``from(\"aws-s3:bucket/key\")`` — S3 sensor trigger.

        Apache Airflow S3KeySensor analogue. Polls S3 head_object до match.
        При match → dsl_service.dispatch.

        Требует ``aioboto3``: ``uv pip install aioboto3``.
        Raises ImportError при construction если не установлен.
        """
        from src.backend.core.orchestration.airflow_sensors import S3Sensor
        from src.backend.core.orchestration.sensor import SensorTrigger
        from src.backend.dsl.orchestration.triggers import (
            FileSensorTaskWrapper as _FileSensorWrapper,
        )
        from src.backend.dsl.orchestration.triggers import get_trigger_registry

        sensor = S3Sensor(
            bucket=bucket,
            key=key,
            region=region,
            endpoint_url=endpoint_url,
            poll_interval_s=poll_interval_s,
        )
        trigger_cfg = SensorTrigger(
            sensor_id=f"s3_{bucket}",
            check=lambda d: asyncio.sleep(0, result=True),
            poll_interval_s=poll_interval_s,
        )

        async def _runner() -> None:
            from src.backend.dsl.service import get_dsl_service

            route_id = getattr(self, "route_id", "") or "_pending_route_"
            while True:
                matched = await sensor.watch(
                    trigger=trigger_cfg, input={}, namespace="default",
                )
                if matched:
                    await get_dsl_service().dispatch(
                        route_id=route_id,
                        body={},
                        headers={
                            "x-sensor": "s3",
                            "x-sensor-bucket": bucket,
                            "x-sensor-key": key,
                        },
                    )
                await asyncio.sleep(poll_interval_s)

        task = _create_or_defer_sensor_task(_runner, name=f"sensor:s3:{bucket}")
        if hasattr(task, "start"):  # _DeferredTask
            get_trigger_registry().register(_FileSensorWrapper(
                task_factory=lambda: task.start(), name=f"sensor:s3:{bucket}",
            ))
        else:
            get_trigger_registry().register(_FileSensorWrapper(task=task, name=f"sensor:s3:{bucket}"))
        return self  # type: ignore

    def sse_source(
        self, url: str, event_types: list[str] | None = None,
    ) -> RouteBuilder:
        """Source-процессор для Server-Sent Events."""
        from src.backend.dsl.engine.processors.generic import SseSourceProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                SseSourceProcessor(url=url, event_types=event_types),
            ),
        )
