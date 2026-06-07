"""DSL Processor Middleware — cross-cutting concerns для pipeline execution.

Middleware выполняется до/после каждого процессора, обеспечивая:
- Timeout enforcement
- Error capture и нормализация
- Metrics collection
- Correlation context propagation
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange

__all__ = ('ErrorNormalizerMiddleware', 'MetricsMiddleware', 'MiddlewareChain', 'ProcessorMiddleware', 'TimeoutMiddleware')
logger = logging.getLogger(__name__)
ProcessFn = Any

class ProcessorMiddleware(ABC):
    """Middleware для DSL-процессоров."""

    @abstractmethod
    async def before(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполнить операцию before."""
        ...

    @abstractmethod
    async def after(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext, error: Exception | None, duration_ms: float) -> None:
        """Выполнить операцию after."""
        ...

class TimeoutMiddleware(ProcessorMiddleware):
    """Enforces per-processor timeout."""

    def __init__(self, default_timeout: float=30.0) -> None:
        """Выполнить операцию   init  ."""
        self._default_timeout = default_timeout
        self._overrides: dict[str, float] = {}

    def set_timeout(self, processor_name: str, timeout: float) -> None:
        """Установить timeout."""
        self._overrides[processor_name] = timeout

    def get_timeout(self, processor_name: str) -> float:
        """Получить timeout."""
        return self._overrides.get(processor_name, self._default_timeout)

    async def before(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполнить операцию before."""
        pass

    async def after(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext, error: Exception | None, duration_ms: float) -> None:
        """Выполнить операцию after."""
        pass

class ErrorNormalizerMiddleware(ProcessorMiddleware):
    """Нормализует ошибки процессоров в единый формат."""

    async def before(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполнить операцию before."""
        pass

    async def after(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext, error: Exception | None, duration_ms: float) -> None:
        """Выполнить операцию after."""
        if error is not None:
            exchange.set_property('_last_error', {'processor': processor_name, 'type': type(error).__name__, 'message': str(error), 'duration_ms': duration_ms})

class MetricsMiddleware(ProcessorMiddleware):
    """Собирает метрики выполнения процессоров."""

    def __init__(self) -> None:
        """Выполнить операцию   init  ."""
        self._totals: dict[str, int] = {}
        self._errors: dict[str, int] = {}
        self._durations: dict[str, list[float]] = {}

    async def before(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Выполнить операцию before."""
        pass

    async def after(self, processor_name: str, exchange: Exchange[Any], context: ExecutionContext, error: Exception | None, duration_ms: float) -> None:
        """Выполнить операцию after."""
        self._totals[processor_name] = self._totals.get(processor_name, 0) + 1
        if error:
            self._errors[processor_name] = self._errors.get(processor_name, 0) + 1
        self._durations.setdefault(processor_name, []).append(duration_ms)
        if len(self._durations[processor_name]) > 1000:
            self._durations[processor_name] = self._durations[processor_name][-500:]

    def get_stats(self) -> dict[str, dict[str, Any]]:
        """Получить stats."""
        stats: dict[str, dict[str, Any]] = {}
        for name, total in self._totals.items():
            durations = self._durations.get(name, [])
            stats[name] = {'total': total, 'errors': self._errors.get(name, 0), 'avg_ms': sum(durations) / len(durations) if durations else 0, 'max_ms': max(durations) if durations else 0}
        return stats

class MiddlewareChain:
    """Цепочка middleware для выполнения вокруг процессора."""

    def __init__(self, middlewares: list[ProcessorMiddleware] | None=None) -> None:
        """Выполнить операцию   init  ."""
        self._middlewares = middlewares or []

    def add(self, middleware: ProcessorMiddleware) -> None:
        """Выполнить операцию add."""
        self._middlewares.append(middleware)

    async def execute(self, processor: Any, exchange: Exchange[Any], context: ExecutionContext, timeout: float | None=None) -> None:
        """Выполнить операцию execute."""
        name = getattr(processor, 'name', processor.__class__.__name__)
        for mw in self._middlewares:
            await mw.before(name, exchange, context)
        start = time.monotonic()
        error: Exception | None = None
        try:
            if timeout:
                await asyncio.wait_for(processor.process(exchange, context), timeout=timeout)
            else:
                await processor.process(exchange, context)
        except TimeoutError:
            error = TimeoutError(f"Processor '{name}' timed out after {timeout}s")
            raise
        except Exception as exc:
            error = exc
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            for mw in reversed(self._middlewares):
                try:
                    await mw.after(name, exchange, context, error, duration_ms)
                except Exception as _:
                    logger.warning('Middleware %s.after() failed', type(mw).__name__)
