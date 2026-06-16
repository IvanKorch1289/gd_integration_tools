"""S55 W2 — flow.py part of control_flow decomp.

Classes: TryCatchProcessor, _RetryAbort, RetryProcessor.
Funcs: .
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus
from src.backend.dsl.engine.processors.base import BaseProcessor, run_sub_processors
from src.backend.dsl.engine.processors.control_flow.saga import _serialize_sub

_cf_logger = get_logger("dsl.control_flow")


class TryCatchProcessor(BaseProcessor):
    """Try/Catch/Finally внутри DSL pipeline.

    Выполняет ``try_processors``. При ошибке — записывает
    исключение в ``exchange.properties["caught_error"]``
    и выполняет ``catch_processors``. ``finally_processors``
    выполняются всегда.
    """

    def __init__(
        self,
        try_processors: list[BaseProcessor],
        catch_processors: list[BaseProcessor] | None = None,
        finally_processors: list[BaseProcessor] | None = None,
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "try_catch")
        self._try = try_processors
        self._catch = catch_processors or []
        self._finally = finally_processors or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        caught = False
        try:
            await run_sub_processors(self._try, exchange, context)
        except Exception as exc:
            caught = True
            exchange.set_property("caught_error", str(exc))
            if exchange.status == ExchangeStatus.failed:
                exchange.status = ExchangeStatus.processing
                exchange.error = None
            await run_sub_processors(self._catch, exchange, context)

        if not caught and exchange.status == ExchangeStatus.failed:
            exchange.set_property("caught_error", exchange.error or "unknown")
            exchange.status = ExchangeStatus.processing
            exchange.error = None
            await run_sub_processors(self._catch, exchange, context)

        for proc in self._finally:
            if exchange.stopped:
                break
            try:
                await proc.process(exchange, context)
            except Exception as exc:
                _cf_logger.error("Finally processor error: %s", exc)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует Try/Catch/Finally в YAML-spec.

        ``None`` если хоть один child sub-pipeline не сериализуется.
        """
        try_sub = _serialize_sub(self._try)
        if try_sub is None:
            return None
        spec: dict[str, Any] = {"try_processors": try_sub}
        if self._catch:
            catch_sub = _serialize_sub(self._catch)
            if catch_sub is None:
                return None
            spec["catch_processors"] = catch_sub
        if self._finally:
            finally_sub = _serialize_sub(self._finally)
            if finally_sub is None:
                return None
            spec["finally_processors"] = finally_sub
        return {"do_try": spec}


class _RetryAbort(Exception):
    """Внутренний маркер для tenacity — извлекаем error из Exchange."""

    def __init__(self, message: str) -> None:
        super().__init__(message)


class RetryProcessor(BaseProcessor):
    """Повторяет sub-pipeline с backoff через ``tenacity`` (ADR-005).

    Раньше здесь был собственный цикл retry — параллельная логика
    с уже установленной ``tenacity``. В A4 реализация переписана как
    тонкая обёртка: tenacity отвечает за стратегии wait/stop/jitter,
    мы — только за правильный сброс состояния ``Exchange`` между
    попытками.

    Args:
        processors: Процессоры для повторного выполнения.
        max_attempts: Максимальное число попыток.
        delay_seconds: Базовая задержка (для exponential — множитель).
        backoff: ``"fixed"`` или ``"exponential"``.
        jitter_seconds: Максимум случайного сдвига (anti-thundering herd).
    """

    def __init__(
        self,
        processors: list[BaseProcessor],
        *,
        max_attempts: int = 3,
        delay_seconds: float = 1.0,
        backoff: str = "exponential",
        jitter_seconds: float = 0.0,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"retry({max_attempts})")
        self._processors = processors
        self._max_attempts = max_attempts
        self._delay = delay_seconds
        self._backoff = backoff
        self._jitter = jitter_seconds

    def _build_wait(self):
        from tenacity import wait_exponential, wait_fixed, wait_random

        if self._backoff == "exponential":
            base = wait_exponential(multiplier=self._delay, min=self._delay, max=60.0)
        else:
            base = wait_fixed(self._delay)
        if self._jitter > 0:
            return base + wait_random(0, self._jitter)
        return base

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from tenacity import AsyncRetrying, RetryError, stop_after_attempt

        last_error: str | None = None
        retrying = AsyncRetrying(
            stop=stop_after_attempt(self._max_attempts),
            wait=self._build_wait(),
            reraise=True,
        )

        try:
            async for attempt in retrying:
                with attempt:
                    # Сброс состояния для повторной попытки
                    if attempt.retry_state.attempt_number > 1:
                        exchange.status = ExchangeStatus.processing
                        exchange.error = None
                        exchange.properties.pop("_stopped", None)

                    for proc in self._processors:
                        if exchange.status == ExchangeStatus.failed or exchange.stopped:
                            break
                        try:
                            await proc.process(exchange, context)
                        except Exception as exc:
                            exchange.fail(str(exc))
                            break

                    if exchange.status == ExchangeStatus.failed:
                        last_error = exchange.error
                        _cf_logger.warning(
                            "Retry %d/%d for '%s' failed: %s",
                            attempt.retry_state.attempt_number,
                            self._max_attempts,
                            self.name,
                            last_error,
                        )
                        raise _RetryAbort(last_error or "failed")
        except RetryError, _RetryAbort:
            exchange.fail(
                f"All {self._max_attempts} attempts failed. Last: {last_error}"
            )

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует Retry-обёртку в YAML-spec.

        Returns:
            ``{"retry": {processors, max_attempts, delay_seconds, backoff,
            jitter_seconds?}}`` или ``None``, если sub-pipeline не сериализуется.
        """
        sub = _serialize_sub(self._processors)
        if sub is None:
            return None
        spec: dict[str, Any] = {
            "processors": sub,
            "max_attempts": self._max_attempts,
            "delay_seconds": self._delay,
            "backoff": self._backoff,
        }
        if self._jitter > 0:
            spec["jitter_seconds"] = self._jitter
        return {"retry": spec}
