"""Мини-HTTP сервер K8s-probes для standalone workflow worker-а (IL-WF1.4).

Экспортирует три endpoint-а на отдельном порту (по умолчанию 9100):

* ``GET /healthz`` — **liveness**. 200 пока процесс работает; в drain-режиме
  отдаёт ``{"status": "draining"}`` (всё ещё 200).
* ``GET /readyz`` — **readiness**. 200 только если ``DurableWorkflowRunner``
  стартовал и (опционально) ``readiness_check()`` вернул True. Иначе 503.
* ``GET /metrics`` — Prometheus text format. Worker-specific gauge'и
  (``workflow_worker_*``) + дефолтный ``REGISTRY``.

Реализация — embedded ``uvicorn`` + ``Starlette`` (роутинг). FastAPI не
нужен (нет валидации/схемы), Starlette уже тянется как зависимость FastAPI.
Один HTTP-сервер в том же event-loop, что и runner.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable

import uvicorn
from prometheus_client import CONTENT_TYPE_LATEST, REGISTRY, Gauge, generate_latest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

__all__ = (
    "WorkerProbesServer",
    "WORKER_ACTIVE_EXECUTIONS",
    "WORKER_QUEUE_DEPTH",
    "WORKER_UP",
)

_logger = logging.getLogger("workflow.worker.probes")


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


ReadinessFn = Callable[[], Awaitable[bool]]


class WorkerProbesServer:
    """ASGI-сервер K8s probes на uvicorn + Starlette в общем event-loop."""

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
        self._server: uvicorn.Server | None = None
        self._serve_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запускает ASGI-сервер на настроенном порту."""
        app = Starlette(
            routes=[
                Route("/healthz", self._handle_healthz),
                Route("/readyz", self._handle_readyz),
                Route("/metrics", self._handle_metrics),
            ]
        )
        config = uvicorn.Config(
            app=app,
            host=self._host,
            port=self._port,
            log_level="warning",
            access_log=False,
            lifespan="off",
        )
        self._server = uvicorn.Server(config)
        self._serve_task = asyncio.create_task(
            self._server.serve(), name="worker-probes-uvicorn"
        )
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
        if self._server is not None:
            self._server.should_exit = True
        if self._serve_task is not None:
            try:
                await asyncio.wait_for(self._serve_task, timeout=5)
            except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
                _logger.warning("probes server stop timeout/cancel: %s", exc)
            except Exception as exc:  # noqa: BLE001
                _logger.warning("probes server stop error: %s", exc)
        _logger.info("probes server stopped")

    def mark_draining(self) -> None:
        """Явно перевести probes в drain-режим (readyz начнёт отдавать 503)."""
        self._draining = True

    async def _handle_healthz(self, _req: Request) -> Response:
        if self._draining:
            return JSONResponse({"status": "draining"}, status_code=200)
        return JSONResponse({"status": "ok"}, status_code=200)

    async def _handle_readyz(self, _req: Request) -> Response:
        if self._draining:
            return JSONResponse(
                {"status": "not_ready", "reason": "draining"}, status_code=503
            )
        if not bool(getattr(self._runner, "_running", False)):
            return JSONResponse(
                {"status": "not_ready", "reason": "runner_not_started"},
                status_code=503,
            )
        if self._readiness_check is not None:
            try:
                ok = await self._readiness_check()
            except Exception as exc:  # noqa: BLE001
                _logger.warning("readiness check error: %s", exc)
                return JSONResponse(
                    {"status": "not_ready", "reason": f"check_error: {exc}"},
                    status_code=503,
                )
            if not ok:
                return JSONResponse(
                    {"status": "not_ready", "reason": "dependency_unhealthy"},
                    status_code=503,
                )
        return JSONResponse({"status": "ready"}, status_code=200)

    async def _handle_metrics(self, _req: Request) -> Response:
        try:
            active = len(getattr(self._runner, "_active_executions", ()) or ())
            queue = getattr(self._runner, "_pending_instance_ids", None)
            qsize = queue.qsize() if queue is not None else 0
            WORKER_ACTIVE_EXECUTIONS.labels(worker_id=self._worker_id).set(active)
            WORKER_QUEUE_DEPTH.labels(worker_id=self._worker_id).set(qsize)
        except Exception as exc:  # noqa: BLE001
            _logger.debug("failed to refresh worker gauges: %s", exc)
        data = generate_latest(REGISTRY)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)
