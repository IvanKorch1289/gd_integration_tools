"""Мини-HTTP сервер K8s-probes для standalone workflow worker-а (IL-WF1.4).

Экспортирует три endpoint-а на отдельном порту (по умолчанию 9100):

* ``GET /healthz`` — **liveness**. 200 пока процесс работает; 503 в
  период graceful-shutdown (после того как worker перешёл в состояние
  ``draining``).
* ``GET /readyz`` — **readiness**. 200 только если:

    - ``DurableWorkflowRunner`` стартовал (``_running == True``),
    - БД-подключение проверено (можно выполнить ``SELECT 1``),
    - LISTEN-подписка установлена (или LISTEN-режим выключен в конфиге).

  Иначе 503 — K8s не направляет трафик в pod.
* ``GET /metrics`` — Prometheus text format. Выдаёт как worker-specific
  метрики (``workflow_worker_*``), так и уже существующие метрики из
  :mod:`app.infrastructure.observability.client_metrics` (``infra_client_*``)
  и прочие, зарегистрированные в дефолтном ``REGISTRY`` prometheus-client.

Реализация — aiohttp (легковесный, не требует FastAPI dependency stack и
не тянет uvicorn). Один server в том же event-loop что и runner.

Интерфейс:

    probes = WorkerProbesServer(
        runner=runner,
        port=9100,
        readiness_check=readiness_fn,
    )
    await probes.start()
    ...
    await probes.stop()
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiohttp import web
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Gauge, generate_latest

__all__ = (
    "WorkerProbesServer",
    "WORKER_ACTIVE_EXECUTIONS",
    "WORKER_QUEUE_DEPTH",
    "WORKER_UP",
)

_logger = logging.getLogger("workflow.worker.probes")

# ── Worker-specific Prometheus метрики ────────────────────────────────

WORKER_ACTIVE_EXECUTIONS = Gauge(
    "workflow_worker_active_executions",
    "Количество инстансов, исполняемых прямо сейчас в этом worker-е.",
    labelnames=("worker_id",),
)

WORKER_QUEUE_DEPTH = Gauge(
    "workflow_worker_queue_depth",
    "Длина in-memory очереди pending workflow_id в worker-е.",
    labelnames=("worker_id",),
)

WORKER_UP = Gauge(
    "workflow_worker_up",
    "1 — worker процесс жив и runner запущен; 0 — shutdown / not ready.",
    labelnames=("worker_id",),
)


# ── HTTP-сервер ───────────────────────────────────────────────────────

ReadinessFn = Callable[[], Awaitable[bool]]


class WorkerProbesServer:
    """aiohttp-based HTTP server для K8s liveness/readiness + /metrics.

    Запускается в одном event-loop c ``DurableWorkflowRunner``, не требует
    дополнительного thread/process. Graceful shutdown — через
    :meth:`stop`.
    """

    def __init__(
        self,
        *,
        runner: Any,
        worker_id: str,
        port: int = 9100,
        host: str = "0.0.0.0",  # noqa: S104 — K8s probes на 0.0.0.0 норма
        readiness_check: ReadinessFn | None = None,
    ) -> None:
        self._runner = runner
        self._worker_id = worker_id
        self._port = port
        self._host = host
        self._readiness_check = readiness_check
        self._draining = False
        self._runner_app: web.Application | None = None
        self._runner_obj: web.AppRunner | None = None
        self._site: web.TCPSite | None = None

    # -- Lifecycle ------------------------------------------------------

    async def start(self) -> None:
        """Запускает HTTP-сервер на настроенном порту."""
        app = web.Application()
        app.router.add_get("/healthz", self._handle_healthz)
        app.router.add_get("/readyz", self._handle_readyz)
        app.router.add_get("/metrics", self._handle_metrics)
        self._runner_app = app
        self._runner_obj = web.AppRunner(app, access_log=None)
        await self._runner_obj.setup()
        self._site = web.TCPSite(self._runner_obj, host=self._host, port=self._port)
        await self._site.start()
        WORKER_UP.labels(worker_id=self._worker_id).set(1)
        _logger.info(
            "probes server started on %s:%s (worker_id=%s)",
            self._host,
            self._port,
            self._worker_id,
        )

    async def stop(self) -> None:
        """Останавливает сервер. Метит ``workflow_worker_up = 0``."""
        self._draining = True
        WORKER_UP.labels(worker_id=self._worker_id).set(0)
        if self._site is not None:
            try:
                await self._site.stop()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("failed to stop probes TCPSite: %s", exc)
        if self._runner_obj is not None:
            try:
                await self._runner_obj.cleanup()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("failed to cleanup probes AppRunner: %s", exc)
        _logger.info("probes server stopped")

    def mark_draining(self) -> None:
        """Явно перевести probes в drain-режим (readyz начнёт отдавать 503).

        Liveness продолжает отдавать 200, пока ``stop()`` не вызван.
        """
        self._draining = True

    # -- Handlers -------------------------------------------------------

    async def _handle_healthz(self, _req: web.Request) -> web.Response:
        """Liveness — 200 пока процесс жив (до физической остановки)."""
        if self._draining:
            # В режиме drain liveness остаётся 200 — иначе K8s убьёт pod
            # до того как активные executions успеют завершиться. Readiness
            # же уже 503 — новый трафик не поступает.
            return web.json_response({"status": "draining"}, status=200)
        return web.json_response({"status": "ok"}, status=200)

    async def _handle_readyz(self, _req: web.Request) -> web.Response:
        """Readiness — 200 только если runner запущен и БД/LISTEN здоровы."""
        if self._draining:
            return web.json_response(
                {"status": "not_ready", "reason": "draining"}, status=503
            )
        running = bool(getattr(self._runner, "_running", False))
        if not running:
            return web.json_response(
                {"status": "not_ready", "reason": "runner_not_started"}, status=503
            )
        if self._readiness_check is not None:
            try:
                ok = await self._readiness_check()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("readiness check error: %s", exc)
                return web.json_response(
                    {"status": "not_ready", "reason": f"check_error: {exc}"}, status=503
                )
            if not ok:
                return web.json_response(
                    {"status": "not_ready", "reason": "dependency_unhealthy"},
                    status=503,
                )
        return web.json_response({"status": "ready"}, status=200)

    async def _handle_metrics(self, _req: web.Request) -> web.Response:
        """Prometheus text export (дефолтный REGISTRY)."""
        # Подтягиваем актуальные значения worker-specific gauge'ей.
        try:
            active = len(getattr(self._runner, "_active_executions", ()) or ())
            queue = getattr(self._runner, "_pending_instance_ids", None)
            qsize = queue.qsize() if queue is not None else 0
            WORKER_ACTIVE_EXECUTIONS.labels(worker_id=self._worker_id).set(active)
            WORKER_QUEUE_DEPTH.labels(worker_id=self._worker_id).set(qsize)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("failed to refresh worker gauges: %s", exc)

        data = generate_latest(REGISTRY)
        return web.Response(body=data, content_type=CONTENT_TYPE_LATEST)
