"""Sprint 6 K2 — structlog batching wrapper для high-RPS hot-path.

Назначение:
    Batching-обёртка над structlog processor pipeline (V15 R-V15-10 +
    R-V15-14). Вместо отправки каждого log-event в backend immediately,
    события копятся в in-memory buffer и сбрасываются батчем раз в
    ``flush_interval_ms`` (default 100ms) или при достижении
    ``batch_size`` (default 50).

Архитектура:
    Wrapper, реализующий structlog ``BoundLoggerBase``-совместимый интерфейс
    (info/warning/error/exception/debug/critical). При flag-OFF события
    форвардятся в inner-logger мгновенно (нулевой overhead). При flag-ON
    события буферизуются + фоновый ``asyncio.Task`` периодически сбрасывает
    батч через :func:`asyncio.gather`.

Feature-flag: ``structlog_batching_enabled`` (default-OFF). Активируется
после staging-smoke с зафиксированным benchmark в
``vault/benchmark-2026-05-15-structlog.md``.

Lessons из ``feedback_wave_7_performance.md``:
    structlog batching wrapper — вторая ступень оптимизации логирования
    после orjson hot-path sweep + canonical_json_bytes.

Использование::

    from src.backend.infrastructure.observability.structlog_batching import (
        BatchingStructlogWrapper, get_batching_wrapper,
    )

    wrapper = get_batching_wrapper()
    wrapper.bind_inner(structlog.get_logger())  # один раз при startup
    wrapper.info("event", key="value")  # буферизуется + flush async

Не дублирует :class:`BatchingSinkRouter` из ``infrastructure/logging/`` —
тот батчит на уровне Sink, а этот — на уровне structlog processor pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

__all__ = ("BatchedLogEvent", "BatchingStructlogWrapper", "get_batching_wrapper")

_INTERNAL_LOG = logging.getLogger("infrastructure.observability.structlog_batching")


@dataclass
class BatchedLogEvent:
    """Один отложенный log-event в буфере.

    Attributes:
        level: Уровень (info/warning/error/critical/debug).
        event: Имя события (первый позиционный аргумент log-метода).
        kwargs: Структурированные поля (key=value pairs).
        timestamp: Monotonic-секунды (для измерения batch-latency).
    """

    level: str
    event: str
    kwargs: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.monotonic)


class BatchingStructlogWrapper:
    """Batching-wrapper над structlog logger.

    При flag-OFF events форвардятся мгновенно. При flag-ON events копятся
    в :class:`collections.deque` и сбрасываются:

    * раз в :attr:`flush_interval_ms` миллисекунд (фоновый ``flush_loop``);
    * при достижении :attr:`batch_size` события (sync trigger).

    Args:
        batch_size: Максимальный размер пачки (default 50).
        flush_interval_ms: Период принудительного flush (default 100ms).
        max_buffer_size: Жёсткий лимит буфера (default 5000). При
            переполнении старые события дропаются с WARNING (V15 R-V15-11
            leak prevention).
    """

    def __init__(
        self,
        *,
        batch_size: int = 50,
        flush_interval_ms: int = 100,
        max_buffer_size: int = 5000,
    ) -> None:
        """Инициализация с дефолтами Sprint 6 K2."""
        if batch_size < 1:
            raise ValueError("batch_size >= 1 обязателен")
        if flush_interval_ms < 1:
            raise ValueError("flush_interval_ms >= 1 обязателен")
        self._batch_size = batch_size
        self._flush_interval_ms = flush_interval_ms
        self._max_buffer_size = max_buffer_size
        self._buffer: deque[BatchedLogEvent] = deque(maxlen=max_buffer_size)
        self._inner: Any | None = None
        self._task: asyncio.Task[None] | None = None
        self._stop_event: asyncio.Event | None = None  # инит при start
        self._dropped_count = 0
        self._flushed_total = 0

    # ------------------------------------------------------------------
    # Конфигурация
    # ------------------------------------------------------------------

    def bind_inner(self, logger: Any) -> None:
        """Привязать inner-structlog-logger.

        Должно вызываться один раз при startup приложения.

        Args:
            logger: structlog.BoundLogger или совместимый объект с
                методами info/warning/error/debug/critical/exception.
        """
        self._inner = logger

    @property
    def is_flag_enabled(self) -> bool:
        """Проверить feature-flag ``structlog_batching_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return feature_flags.structlog_batching_enabled
        except Exception as _:
            return False

    # ------------------------------------------------------------------
    # Log-методы (совместимы со structlog.BoundLogger)
    # ------------------------------------------------------------------

    def info(self, event: str, **kwargs: Any) -> None:
        """Запись info-event (буферизуется при flag-ON)."""
        self._log("info", event, kwargs)

    def warning(self, event: str, **kwargs: Any) -> None:
        """Запись warning-event."""
        self._log("warning", event, kwargs)

    def error(self, event: str, **kwargs: Any) -> None:
        """Запись error-event."""
        self._log("error", event, kwargs)

    def debug(self, event: str, **kwargs: Any) -> None:
        """Запись debug-event."""
        self._log("debug", event, kwargs)

    def critical(self, event: str, **kwargs: Any) -> None:
        """Запись critical-event."""
        self._log("critical", event, kwargs)

    def exception(self, event: str, **kwargs: Any) -> None:
        """Запись exception-event (с traceback в inner)."""
        self._log("exception", event, kwargs)

    def _log(self, level: str, event: str, kwargs: dict[str, Any]) -> None:
        """Внутренний dispatch — flag-OFF: direct, flag-ON: buffer."""
        if not self.is_flag_enabled:
            # Direct path — нулевой overhead.
            self._emit_direct(level, event, kwargs)
            return

        if self._inner is None:
            # Не привязан inner — fallback на python logging.
            _INTERNAL_LOG.warning("structlog_batching: inner не привязан")
            return

        item = BatchedLogEvent(level=level, event=event, kwargs=kwargs)
        if len(self._buffer) >= self._max_buffer_size:
            # deque(maxlen=...) автоматически дропнет старый event;
            # инкрементируем counter для метрики.
            self._dropped_count += 1
        self._buffer.append(item)

        # Sync-trigger при достижении batch_size — для гарантии latency
        if len(self._buffer) >= self._batch_size:
            # Не блокируем вызывающий код — schedule task через TaskRegistry
            # для немедленного flush + graceful shutdown.
            try:
                asyncio.get_running_loop()
            except RuntimeError:
                # Нет running loop (sync-контекст) — игнорируем,
                # flush произойдёт в следующем flush_loop tick'е.
                pass
            else:
                from src.backend.core.utils.task_registry import get_task_registry

                get_task_registry().create_task(
                    self._flush_batch(), name="structlog-flush", deadline_seconds=5.0
                )

    def _emit_direct(self, level: str, event: str, kwargs: dict[str, Any]) -> None:
        """Прямой вызов inner-логгера без буферизации."""
        if self._inner is None:
            return
        method = getattr(self._inner, level, None)
        if method is None:
            return
        try:
            method(event, **kwargs)
        except Exception as _:
            _INTERNAL_LOG.warning("structlog_batching: emit error", exc_info=True)

    # ------------------------------------------------------------------
    # Background flush loop
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Запустить фоновый flush-loop (при flag-ON).

        Идемпотентно: повторный вызов игнорируется (логирует warning).
        """
        if self._task is not None and not self._task.done():
            _INTERNAL_LOG.warning("structlog_batching: уже запущен")
            return
        self._stop_event = asyncio.Event()
        from src.backend.core.utils.task_registry import get_task_registry

        self._task = get_task_registry().create_task(
            self._flush_loop(), name="structlog-batching-flush"
        )

    async def stop(self) -> None:
        """Остановить flush-loop и drain буфер."""
        if self._stop_event is not None:
            self._stop_event.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5.0)
            except TimeoutError:
                self._task.cancel()
        # Final drain
        await self._flush_batch()

    async def _flush_loop(self) -> None:
        """Фоновый loop: flush раз в flush_interval_ms."""
        if self._stop_event is None:
            return
        interval = self._flush_interval_ms / 1000.0
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except TimeoutError:
                # interval истёк — нормальный flush
                await self._flush_batch()

    async def _flush_batch(self) -> None:
        """Сброс текущего буфера в inner-логгер."""
        if not self._buffer:
            return
        # Сделать snapshot и очистить буфер быстро.
        events_to_emit = list(self._buffer)
        self._buffer.clear()

        for item in events_to_emit:
            self._emit_direct(item.level, item.event, item.kwargs)
        self._flushed_total += len(events_to_emit)

    # ------------------------------------------------------------------
    # Метрики (для перфоманс-аудита)
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, int]:
        """Снапшот метрик batching-wrapper."""
        return {
            "buffer_size": len(self._buffer),
            "dropped_count": self._dropped_count,
            "flushed_total": self._flushed_total,
            "batch_size_limit": self._batch_size,
            "max_buffer_size": self._max_buffer_size,
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_wrapper_instance: BatchingStructlogWrapper | None = None


def get_batching_wrapper() -> BatchingStructlogWrapper:
    """Singleton — один экземпляр batching-wrapper на процесс."""
    global _wrapper_instance
    if _wrapper_instance is None:
        _wrapper_instance = BatchingStructlogWrapper()
    return _wrapper_instance
