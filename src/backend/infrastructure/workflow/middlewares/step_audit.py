"""K3 S5 W11 — :class:`StepAuditMiddleware` → ClickHouse workflow_step_log.

Wave ``[wave:s5/k3-w11-step-log-clickhouse]``.

Middleware для оборачивания выполнения workflow-шагов:
* записывает event (workflow_id, step_id, step_name, correlation_id, tenant_id,
  duration_ms, status, input/output_schema_hash, ts) в ClickHouse;
* выставляет OTel custom span attributes (workflow.step.name,
  workflow.step.duration_ms, workflow.step.status);
* batching через async ``flush_interval_s`` (минимизирует round-trip в CH);
* error-swallow: middleware никогда не bubble-up ошибки в caller.

Контракт использования::

    middleware = StepAuditMiddleware(clickhouse_client=ch, flush_interval_s=2.0)
    await middleware.start()
    # ... workflow выполняется ...
    async with middleware.track_step(
        workflow_id="wf-1",
        step_name="fetch_score",
        tenant_id="acme",
    ) as ctx:
        ctx.input_schema_hash = "abc..."
        result = await activity()
        ctx.output_schema_hash = "def..."
    await middleware.stop()

Feature flag: ``feature_flags.workflow_step_log_enabled`` (default-OFF).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

__all__ = (
    "PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL",
    "StepAuditEvent",
    "StepAuditMiddleware",
)


_logger = logging.getLogger("infrastructure.workflow.middlewares.step_audit")


# DDL для ClickHouse-таблицы workflow_step_log.
PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL = """
CREATE TABLE IF NOT EXISTS workflow_step_log (
    event_id String,
    workflow_id String,
    step_id String,
    step_name String,
    correlation_id String,
    tenant_id String,
    duration_ms Float64,
    status String,
    input_schema_hash String,
    output_schema_hash String,
    ts DateTime64(3) DEFAULT now64(3)
) ENGINE = MergeTree()
ORDER BY (workflow_id, ts);
""".strip()


@dataclass(slots=True)
class StepAuditEvent:
    """Одна запись в workflow_step_log."""

    workflow_id: str
    step_name: str
    duration_ms: float
    status: str
    step_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = ""
    tenant_id: str = ""
    input_schema_hash: str = ""
    output_schema_hash: str = ""
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    ts: float = field(default_factory=time.time)

    def to_row(self) -> dict[str, Any]:
        return {
            "event_id": self.event_id,
            "workflow_id": self.workflow_id,
            "step_id": self.step_id,
            "step_name": self.step_name,
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "input_schema_hash": self.input_schema_hash,
            "output_schema_hash": self.output_schema_hash,
            "ts": self.ts,
        }


@dataclass(slots=True)
class _StepContext:
    """Mutable-контекст внутри ``track_step``."""

    input_schema_hash: str = ""
    output_schema_hash: str = ""


def schema_hash(payload: Any) -> str:
    """SHA-256 hash от структуры payload (для schema-fingerprint)."""
    if payload is None:
        return ""
    try:
        import orjson

        data = orjson.dumps(payload, default=str)
    except Exception:  # noqa: BLE001
        data = str(payload).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


class StepAuditMiddleware:
    """Middleware для аудита workflow-шагов в ClickHouse.

    Args:
        clickhouse_client: Async ClickHouse-клиент с методом ``insert(table, rows)``.
            Если ``None`` — middleware работает в no-op режиме (логирует только).
        flush_interval_s: Интервал автоматического flush в CH (default 2s).
        batch_size: Максимальный размер batch перед flush (default 100).
    """

    def __init__(
        self,
        clickhouse_client: Any | None = None,
        *,
        flush_interval_s: float = 2.0,
        batch_size: int = 100,
    ) -> None:
        self._client = clickhouse_client
        self._flush_interval_s = flush_interval_s
        self._batch_size = batch_size
        self._buffer: list[StepAuditEvent] = []
        self._lock = asyncio.Lock()
        self._stop_event = asyncio.Event()
        self._flusher_task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запустить background-flusher task."""
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.workflow_step_log_enabled:
                _logger.info("StepAuditMiddleware: feature-flag OFF, no-op mode")
                return
        except Exception:  # noqa: BLE001
            pass

        if self._flusher_task is not None:
            return
        self._stop_event.clear()
        from src.backend.core.utils.task_registry import (
            get_task_registry,  # noqa: PLC0415
        )

        self._flusher_task = get_task_registry().create_task(
            self._flusher_loop(), name="step-audit-flusher"
        )

    async def stop(self) -> None:
        """Остановить flusher и сбросить остаток buffer."""
        self._stop_event.set()
        if self._flusher_task is not None:
            try:
                await asyncio.wait_for(self._flusher_task, timeout=5.0)
            except asyncio.TimeoutError:
                self._flusher_task.cancel()
            self._flusher_task = None
        await self.flush()

    async def flush(self) -> None:
        """Сбросить текущий buffer в ClickHouse (error-swallow)."""
        async with self._lock:
            if not self._buffer:
                return
            rows = [event.to_row() for event in self._buffer]
            self._buffer.clear()

        if self._client is None:
            _logger.debug("StepAuditMiddleware flush (no-op): %d rows", len(rows))
            return
        try:
            insert = getattr(self._client, "insert", None)
            if insert and asyncio.iscoroutinefunction(insert):
                await insert("workflow_step_log", rows)
            elif insert:
                insert("workflow_step_log", rows)
        except Exception as exc:  # noqa: BLE001
            _logger.error("StepAuditMiddleware flush failed: %s", exc)

    @asynccontextmanager
    async def track_step(
        self,
        *,
        workflow_id: str,
        step_name: str,
        correlation_id: str = "",
        tenant_id: str = "",
    ) -> AsyncIterator[_StepContext]:
        """Контекстный менеджер для отслеживания одного шага."""
        ctx = _StepContext()
        started = time.perf_counter()
        status = "ok"
        # OTel attribute setup
        self._set_otel_attrs(step_name=step_name, started=True)
        try:
            yield ctx
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = (time.perf_counter() - started) * 1000.0
            event = StepAuditEvent(
                workflow_id=workflow_id,
                step_name=step_name,
                duration_ms=duration_ms,
                status=status,
                correlation_id=correlation_id,
                tenant_id=tenant_id,
                input_schema_hash=ctx.input_schema_hash,
                output_schema_hash=ctx.output_schema_hash,
            )
            self._set_otel_attrs(
                step_name=step_name, duration_ms=duration_ms, status=status
            )
            async with self._lock:
                self._buffer.append(event)
                if len(self._buffer) >= self._batch_size:
                    # Trigger immediate flush in background
                    from src.backend.core.utils.task_registry import (  # noqa: PLC0415
                        get_task_registry,
                    )

                    get_task_registry().create_task(
                        self.flush(), name="step-audit-immediate-flush"
                    )

    def _set_otel_attrs(
        self,
        *,
        step_name: str,
        duration_ms: float | None = None,
        status: str | None = None,
        started: bool = False,
    ) -> None:
        """Best-effort OTel span attribute set (no-op без подключения OTel)."""
        try:
            from opentelemetry import trace as _otel_trace

            span = _otel_trace.get_current_span()
            if not span or not span.is_recording():
                return
            span.set_attribute("workflow.step.name", step_name)
            if duration_ms is not None:
                span.set_attribute("workflow.step.duration_ms", duration_ms)
            if status is not None:
                span.set_attribute("workflow.step.status", status)
        except ImportError:
            pass
        except Exception:  # noqa: BLE001
            pass

    async def _flusher_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self._flush_interval_s
                )
            except asyncio.TimeoutError:
                pass
            await self.flush()
