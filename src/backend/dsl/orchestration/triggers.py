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
    "IntervalTrigger",
    "FileSensorTaskWrapper",
    "Trigger",
    "TriggerRegistry",
    "WebhookTrigger",
    "get_trigger_registry",
)


class FileSensorTaskWrapper:
    """Wrapper для background-task-based sensors (file/sql/http/s3).

    Имплементирует Trigger Protocol для совместимости с TriggerRegistry.
    """

    def __init__(self, task: asyncio.Task) -> None:  # type: ignore[type-arg]
        self.name = f"sensor_task_{id(task)}"
        self._task = task

    async def start(self) -> None:
        # Task already started in DSL builder; this is no-op
        pass

    async def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError, Exception:
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

        async def _loop() -> None:
            if self._start_immediately:
                await self._dispatch()
            while not self._stop.is_set():
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=self.interval_s)
                except asyncio.TimeoutError:
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
        self._stop.set()
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError, Exception:
                pass
            self._task = None
        _log.info("IntervalTrigger: %s stopped", self.name)

    async def _dispatch(self) -> None:
        from src.backend.dsl.service import get_dsl_service

        body = self._payload() if callable(self._payload) else self._payload
        try:
            await get_dsl_service().dispatch(
                route_id=self.route_id, body=body, headers={"x-trigger": self.name}
            )
        except Exception:
            _log.exception("IntervalTrigger %s: dispatch failed", self.name)


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
        if self._route_added:
            return
        # Try to find FastAPI app from common locations
        app = self._app
        if app is None:
            try:
                from src.backend.entrypoints.api.app import get_app  # type: ignore[import-not-found]  # noqa: I001

                app = get_app()
            except Exception:
                _log.warning(
                    "WebhookTrigger %s: no FastAPI app found, deferring", self.name
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
            except Exception as e:
                _log.exception("WebhookTrigger %s: dispatch failed", self.name)
                return {"status": "error", "error": str(e)}

        app.add_api_route(
            self.path, _handler, methods=[self.method], name=f"webhook_{self.name}"
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
        if self._app is not None and self._route_added:
            try:
                self._app.router.routes = [
                    r
                    for r in self._app.router.routes
                    if getattr(r, "name", "") != f"webhook_{self.name}"
                ]
            except Exception:
                pass
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
        with self._lock:
            if trigger.name in self._triggers:
                _log.warning("Trigger %s already registered, replacing", trigger.name)
            self._triggers[trigger.name] = trigger

    def unregister(self, name: str) -> None:
        with self._lock:
            self._triggers.pop(name, None)

    def get(self, name: str) -> Trigger | None:
        with self._lock:
            return self._triggers.get(name)

    def list_names(self) -> list[str]:
        with self._lock:
            return list(self._triggers.keys())

    async def start_all(self) -> None:
        with self._lock:
            triggers = list(self._triggers.values())
        for t in triggers:
            try:
                await t.start()
            except Exception:
                _log.exception("Trigger %s start failed", t.name)

    async def stop_all(self) -> None:
        with self._lock:
            triggers = list(self._triggers.values())
        for t in triggers:
            try:
                await t.stop()
            except Exception:
                _log.exception("Trigger %s stop failed", t.name)


_REGISTRY: TriggerRegistry | None = None


def get_trigger_registry() -> TriggerRegistry:
    """Singleton accessor."""
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = TriggerRegistry()
    return _REGISTRY
