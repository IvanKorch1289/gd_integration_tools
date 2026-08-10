"""Route Triggers DSL: Camel-style ``from(...)`` builders (S55 W4).

Apache Camel: каждый route начинается с ``from("timer:foo")`` / ``from("kafka:...")``
или подобного source'а. Здесь — DSL-методы на RouteBuilder, которые bind'ят
trigger к route.

Триггеры:
* :func:`from_cron` — уже существует как :func:`schedule` (cron-выражение)
* :func:`from_interval` — каждые N секунд (uses apscheduler IntervalTrigger)
* :func:`from_webhook` — HTTP webhook → route (FastAPI route + POST handler)
* :func:`from_file` — file/glob appearance → route (uses FileSensor)

Архитектура: :class:`TriggerRegistry` — singleton, хранит активные triggers,
предоставляет start_all/stop_all. Каждый trigger при match вызывает
``dsl_service.dispatch(route_id, body, headers)``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Protocol

from src.backend.core.logging import get_logger

__all__ = (
    "FileSensorTaskWrapper",
    "IntervalTrigger",
    "Trigger",
    "TriggerRegistry",
    "WebhookTrigger",
    "get_trigger_registry",
)


class FileSensorTaskWrapper:
    """Wrapper для background-task-based sensors (file/sql/http/s3).

    Имплементирует Trigger Protocol для совместимости с TriggerRegistry.

    Cycle 46: supports lazy task creation. If DSL is built outside an
    event loop (sync context), pass ``task_factory`` instead of ``task``.
    The task is then created when :meth:`start` is called from an async
    context (e.g., during app startup).
    """

    def __init__(
        self,
        task: asyncio.Task | None = None,
        *,
        task_factory: Callable[[], asyncio.Task] | None = None,
        name: str | None = None,
    ) -> None:
        if task is None and task_factory is None:
            raise ValueError(
                "FileSensorTaskWrapper: either `task` or `task_factory` required",
            )
        self.name = name or f"sensor_task_{id(task) if task else id(object())}"
        self._task = task
        self._task_factory = task_factory

    @property
    def task(self) -> asyncio.Task | None:
        """Returns the underlying task (may be None until :meth:`start` is called)."""
        return self._task

    async def start(self) -> None:
        """Cycle 46: create task lazily if not already created.

        If task was created at DSL build time (running event loop),
        this is no-op. Otherwise, create task now using ``task_factory``.
        Idempotent: factory called only once (subsequent start() are no-op).
        """
        if self._task is not None:
            return  # already running (created at construction or earlier start)
        if self._task_factory is not None:
            self._task = self._task_factory()

    async def stop(self) -> None:
        """Cancel underlying task и await с swallow CancelledError/Exception."""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass


# Backward-compat alias (was used in eip.py before refactor)
_FileSensorWrapper = FileSensorTaskWrapper

_log = get_logger(__name__)


class Trigger(Protocol):
    """Protocol для route trigger."""

    name: str

    async def start(self) -> None:
        """Запустить trigger."""
        ...

    async def stop(self) -> None:
        """Остановить trigger."""
        ...


# ── IntervalTrigger ────────────────────────────────────────────────


class IntervalTrigger:
    """Периодический запуск route каждые ``interval_s`` секунд.

    Uses APScheduler IntervalTrigger (already in deps).

    Args:
        name: имя trigger (для логов).
        route_id: route для dispatch.
        interval_s: interval в секундах.
        start_immediately: запустить сразу или после первого interval.
        payload: factory для payload (может быть static dict или callable).

    """

    def __init__(
        self,
        name: str,
        route_id: str,
        interval_s: float,
        *,
        start_immediately: bool = False,
        payload: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        self.name = name
        self.route_id = route_id
        self.interval_s = interval_s
        self._start_immediately = start_immediately
        self._payload = payload or {}
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Запускает background loop: dispatch payload с interval_s, опционально immediate.

        Layer 9 RPA Cycle 2 fix: idempotent guard — если start() вызван
        повторно без stop(), возвращаемся без создания нового task
        (предотвращает утечку asyncio.Task).
        """
        if self._task and not self._task.done():
            _log.debug(
                "IntervalTrigger: %s already running, skipping duplicate start",
                self.name,
            )
            return

        async def _loop() -> None:
            if self._start_immediately:
                await self._dispatch()
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                except TimeoutError:
                    pass
                if self._stop.is_set():
                    return
                await self._dispatch()

        self._task = asyncio.create_task(_loop(), name=f"trigger:{self.name}")
        _log.info(
            "IntervalTrigger: %s started (route=%s, interval=%.1fs)",
            self.name,
            self.route_id,
            self.interval_s,
        )

    async def stop(self) -> None:
        """Signal stop event, cancel task, await с swallow exception."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        _log.info("IntervalTrigger: %s stopped", self.name)

    async def _dispatch(self) -> None:
        from src.backend.dsl.service import get_dsl_service

        body = self._payload() if callable(self._payload) else self._payload
        try:
            await get_dsl_service().dispatch(
                route_id=self.route_id, body=body, headers={"x-trigger": self.name},
            )
        except (ImportError, AttributeError, RuntimeError, ConnectionError, OSError) as dispatch_exc:
            # cycle-9/D-AUDIT-968: narrow exceptions + observability.
            # ImportError — DSL service missing, AttributeError — service
            # API change, RuntimeError — dispatch failure, ConnectionError/
            # OSError — backend unavailable.
            _log.exception(
                "IntervalTrigger %s: dispatch failed: %s",
                self.name,
                dispatch_exc,
            )

    async def tick(self) -> bool:
        """Manual tick — возвращает True если trigger должен dispatch'ить сейчас.

        S168 W10 P1-2: helper для CronTrigger. APScheduler CronTrigger
        сам вычисляет next_fire_time; мы используем её для проверки.
        """
        return True


class CronTrigger:
    """Cron-выражение для периодического запуска route (S168 W10 P1-2).

    Uses APScheduler ``CronTrigger.from_crontab`` (canonical scheduler;
    already in deps as ``apscheduler>=3.11.0,<4.0.0``).

    Отличие от ``RouteBuilder.schedule(cron=...)``:
    - ``schedule(cron=...)`` — defers single execution до next cron tick.
    - ``from_cron(cron_expr)`` — real periodic dispatch (loop until stop).

    Args:
        name: имя trigger (для логов).
        route_id: route для dispatch.
        cron_expr: 5-field cron expression (e.g. ``"*/5 * * * *"``).
        timezone_name: IANA timezone name (default UTC).
        payload: factory для payload.

    """

    def __init__(
        self,
        name: str,
        route_id: str,
        cron_expr: str,
        *,
        timezone_name: str = "UTC",
        payload: dict[str, Any] | Callable[[], dict[str, Any]] | None = None,
    ) -> None:
        from apscheduler.triggers.cron import CronTrigger as _APSCron

        self.name = name
        self.route_id = route_id
        self.cron_expr = cron_expr
        self.timezone_name = timezone_name
        self._payload = payload or {}
        self._aps_trigger = _APSCron.from_crontab(cron_expr, timezone=timezone_name)
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        """Запускает background loop: вычисляет next_fire_time, sleep до tick.

        Layer 9 RPA Cycle 2 fix: idempotent guard (см. IntervalTrigger.start).
        """
        if self._task and not self._task.done():
            _log.debug(
                "CronTrigger: %s already running, skipping duplicate start",
                self.name,
            )
            return

        import datetime as _dt

        async def _loop() -> None:
            while not self._stop.is_set():
                now = _dt.datetime.now(_dt.UTC)
                next_fire = self._aps_trigger.get_next_fire_time(None, now)
                if next_fire is None:
                    return  # cron expression yields no future fire
                sleep_s = max(0.0, (next_fire - now).total_seconds())
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=sleep_s)
                except TimeoutError:
                    pass
                if self._stop.is_set():
                    return
                await self._dispatch()

        self._task = asyncio.create_task(_loop(), name=f"trigger:{self.name}")
        _log.info(
            "CronTrigger: %s started (route=%s, cron=%r, tz=%s)",
            self.name,
            self.route_id,
            self.cron_expr,
            self.timezone_name,
        )

    async def stop(self) -> None:
        """Signal stop event, cancel task."""
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
            self._task = None
        _log.info("CronTrigger: %s stopped", self.name)

    async def _dispatch(self) -> None:
        from src.backend.dsl.service import get_dsl_service

        body = self._payload() if callable(self._payload) else self._payload
        try:
            await get_dsl_service().dispatch(
                route_id=self.route_id, body=body, headers={"x-trigger": self.name},
            )
        except (ImportError, AttributeError, RuntimeError, ConnectionError, OSError) as dispatch_exc:
            # cycle-9/D-AUDIT-969: narrow exceptions + observability (mirror
            # D-AUDIT-968 для IntervalTrigger).
            _log.exception(
                "CronTrigger %s: dispatch failed: %s",
                self.name,
                dispatch_exc,
            )


# ── WebhookTrigger ─────────────────────────────────────────────────


class WebhookTrigger:
    """HTTP webhook trigger: POST /<path> → route.

    Регистрирует FastAPI route через app.add_api_route. При вызове
    (с любым JSON body) → dsl_service.dispatch(route_id, body, headers).

    Args:
        name: имя trigger.
        route_id: route для dispatch.
        path: URL path (e.g., "/webhooks/orders").
        method: HTTP method (default POST).
        app: FastAPI app instance (если None — берётся из app context).

    """

    def __init__(
        self,
        name: str,
        route_id: str,
        path: str,
        *,
        method: str = "POST",
        app: Any | None = None,
    ) -> None:
        self.name = name
        self.route_id = route_id
        self.path = path
        self.method = method.upper()
        self._app = app
        self._route_added = False

    async def start(self) -> None:
        """Регистрирует FastAPI route для webhook → DSL dispatch (idempotent)."""
        if self._route_added:
            return
        # Try to find FastAPI app from common locations.
        # Documented graceful cross-layer lookup (Phase 2 fix, ADR-???):
        # entrypoints module is optional (dev_light build may omit it),
        # so this fallback is intentional and protected by try/except.
        # When ``core.di.providers.http.get_app_provider()`` lands, replace
        # this fallback with a typed provider call.
        app = self._app
        if app is None:
            try:
                from src.backend.entrypoints.api.app import get_app  # type: ignore[import-not-found]

                app = get_app()
            except (ImportError, AttributeError, RuntimeError) as app_exc:
                # cycle-9/D-AUDIT-1017: narrow exceptions + observability.
                # ImportError — get_app missing, AttributeError — API
                # change, RuntimeError — FastAPI app unavailable.
                _log.warning(
                    "WebhookTrigger %s: no FastAPI app found, deferring: %s",
                    self.name,
                    app_exc,
                )
                return

        async def _handler(body: dict[str, Any] | None = None) -> dict[str, str]:
            from src.backend.dsl.service import get_dsl_service

            try:
                await get_dsl_service().dispatch(
                    route_id=self.route_id,
                    body=body or {},
                    headers={"x-webhook": self.name, "x-webhook-path": self.path},
                )
                return {"status": "dispatched", "route_id": self.route_id}
            except (ImportError, AttributeError, RuntimeError, ConnectionError, OSError, TypeError, ValueError) as dispatch_exc:
                # cycle-9/D-AUDIT-970: narrow exceptions + observability (mirror
                # D-AUDIT-968/969 для WebhookTrigger). TypeError/ValueError
                # включены т.к. body может быть malformed.
                _log.exception("WebhookTrigger %s: dispatch failed: %s", self.name, dispatch_exc)
                return {"status": "error", "error": str(dispatch_exc)}

        app.add_api_route(
            self.path, _handler, methods=[self.method], name=f"webhook_{self.name}",
        )
        self._route_added = True
        _log.info(
            "WebhookTrigger: %s registered %s %s → %s",
            self.name,
            self.method,
            self.path,
            self.route_id,
        )

    async def stop(self) -> None:
        """Удаляет webhook route из FastAPI router (best-effort)."""
        if self._app is not None and self._route_added:
            try:
                self._app.router.routes = [
                    r
                    for r in self._app.router.routes
                    if getattr(r, "name", "") != f"webhook_{self.name}"
                ]
            except (AttributeError, TypeError, RuntimeError) as router_exc:
                # cycle-9/D-AUDIT-971: narrow exceptions + observability.
                # AttributeError — router API change, TypeError — wrong
                # routes type, RuntimeError — router mutated concurrently.
                import logging
                logging.getLogger(__name__).debug(
                    "WebhookTrigger.router_unmount_failed",
                    extra={"name": self.name, "error": str(router_exc)},
                )
        self._route_added = False
        _log.info("WebhookTrigger: %s stopped", self.name)


# ── TriggerRegistry ────────────────────────────────────────────────


class TriggerRegistry:
    """Singleton registry для всех активных triggers.

    start_all() запускает все зарегистрированные triggers.
    stop_all() останавливает все (при shutdown).
    """

    def __init__(self) -> None:
        self._triggers: dict[str, Trigger] = {}
        self._lock = threading.Lock()

    def register(self, trigger: Trigger) -> None:
        """Регистрирует trigger по name (replace если уже есть, с warning)."""
        with self._lock:
            if trigger.name in self._triggers:
                _log.warning("Trigger %s already registered, replacing", trigger.name)
            self._triggers[trigger.name] = trigger

    def unregister(self, name: str) -> None:
        """Удаляет trigger по name (no-op если нет)."""
        with self._lock:
            self._triggers.pop(name, None)

    def get(self, name: str) -> Trigger | None:
        """Возвращает trigger по name или None."""
        with self._lock:
            return self._triggers.get(name)

    def list_names(self) -> list[str]:
        """Возвращает список зарегистрированных trigger names."""
        with self._lock:
            return list(self._triggers.keys())

    async def start_all(self) -> None:
        """Запускает все triggers sequentially (errors swallowed per trigger)."""
        with self._lock:
            triggers = list(self._triggers.values())
        for t in triggers:
            try:
                await t.start()
            except (ImportError, AttributeError, RuntimeError, ConnectionError, OSError) as start_exc:
                # cycle-9/D-AUDIT-972: narrow exceptions + observability.
                # ImportError — trigger dep missing, AttributeError — API
                # change, RuntimeError — start failure, ConnectionError/
                # OSError — backend unavailable.
                _log.exception("Trigger %s start failed: %s", t.name, start_exc)

    async def stop_all(self) -> None:
        """Останавливает все triggers sequentially (errors swallowed per trigger)."""
        with self._lock:
            triggers = list(self._triggers.values())
        for t in triggers:
            try:
                await t.stop()
            except (ImportError, AttributeError, RuntimeError, ConnectionError, OSError) as stop_exc:
                # cycle-9/D-AUDIT-1018: narrow exceptions + observability (mirror
                # D-AUDIT-972 для start_all).
                # ImportError — trigger dep missing, AttributeError —
                # API change, RuntimeError — stop failure, ConnectionError/
                # OSError — backend unavailable.
                _log.exception("Trigger %s stop failed: %s", t.name, stop_exc)


_REGISTRY: TriggerRegistry | None = None


def get_trigger_registry() -> TriggerRegistry:
    """Singleton accessor."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = TriggerRegistry()
    return _REGISTRY
