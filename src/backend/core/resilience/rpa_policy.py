"""RPACallPolicy — единый resilience-фасад для RPA/CDC/FileWatcher/Webhook/DesktopRPA.

Источник: PLAN.md V22.2 §4 + ADR-NEW-13 + B-02 closure.

Назначение:
    Композирует retry (exponential backoff) + circuit breaker + DLQ + audit
    для пяти transport-классов с общим API. Закрывает B-02 — события
    больше не теряются в ad-hoc try/except.

Использование:
    Объект создаётся в композиционном корне (lifespan) и инжектируется
    в RPA-callsites. На каждое внешнее обращение transport-логика
    обёртывается через :meth:`call`:

    .. code-block:: python

        async def acquire_with_policy(self):
            return await policy.call(
                self._do_acquire,
                transport="browser_pool",
            )

    При отключённом feature-flag ``rpa_resilience_wrapper_enabled`` —
    ``call(coro_factory)`` просто вызывает ``coro_factory()`` (passthrough).

См. также:
    * :class:`src.backend.core.messaging.dlq.DLQWriter` — DLQ destination.
    * :mod:`src.backend.core.resilience.breaker` — Breaker for CB stage.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger

import asyncio

import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC
from typing import Any, TypeVar

from src.backend.core.config.features import feature_flags
from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason, DLQWriter

__all__ = (
    "RPACallContext",
    "RPACallExhausted",
    "RPACallPolicy",
    "RPACallResult",
    "get_rpa_policy",
    "set_rpa_policy",
)

_logger = get_logger(__name__)

T = TypeVar("T")


class RPACallExhausted(RuntimeError):
    """Все retry-попытки исчерпаны; событие отправлено в DLQ."""

    def __init__(self, transport: str, last_error: BaseException) -> None:
        self.transport = transport
        self.last_error = last_error
        super().__init__(
            f"RPA call '{transport}' exhausted: "
            f"{type(last_error).__name__}: {last_error}"
        )


@dataclass(slots=True)
class RPACallContext:
    """Контекст одного call(): фиксирует попытки и таймстампы."""

    transport: str
    tenant_id: str | None = None
    route_id: str | None = None
    payload: Any = None
    attempts: int = 0
    first_failed_at_ts: float | None = None
    last_failed_at_ts: float | None = None
    last_error: BaseException | None = None


@dataclass(slots=True)
class RPACallResult:
    """Результат успешного call() (для observability hook)."""

    transport: str
    attempts: int
    duration_seconds: float


@dataclass(slots=True)
class _BreakerLike:
    """Минимальный Breaker contract — only what RPACallPolicy needs."""

    is_open: Callable[[], bool] = field(default=lambda: False)
    on_success: Callable[[], None] = field(default=lambda: None)
    on_failure: Callable[[], None] = field(default=lambda: None)


class RPACallPolicy:
    """Единая resilience-обёртка для RPA/CDC/FileWatcher/Webhook/DesktopRPA.

    Args:
        name: Уникальное имя экземпляра (для логов / метрик).
        max_attempts: Сколько раз повторять до DLQ (default 3).
        backoff_initial_seconds: Стартовый interval (default 1s).
        backoff_max_seconds: Cap для экспоненциального backoff (default 30s).
        jitter: Случайный jitter ratio (0..1); default 0.3.
        breaker: Опц. Breaker-like объект (``is_open/on_success/on_failure``).
        dlq_writer: Опц. ``DLQWriter`` для exhausted attempts.
        on_attempt: Callback ``(ctx, attempt_index, error)`` — для audit/observability.
        retryable_exceptions: tuple исключений, которые triger retry. Иные
            — fail-fast в DLQ. Default — все ``Exception`` (без ``BaseException``).
    """

    def __init__(
        self,
        name: str,
        *,
        max_attempts: int = 3,
        backoff_initial_seconds: float = 1.0,
        backoff_max_seconds: float = 30.0,
        jitter: float = 0.3,
        breaker: _BreakerLike | None = None,
        dlq_writer: DLQWriter | None = None,
        on_attempt: Callable[[RPACallContext, int, BaseException | None], None]
        | None = None,
        retryable_exceptions: tuple[type[BaseException], ...] = (Exception,),
    ) -> None:
        if max_attempts < 1:
            raise ValueError(f"max_attempts должен быть >= 1, получено {max_attempts}")
        self.name = name
        self.max_attempts = max_attempts
        self.backoff_initial = backoff_initial_seconds
        self.backoff_max = backoff_max_seconds
        self.jitter = max(0.0, min(jitter, 1.0))
        self._breaker = breaker
        self._dlq_writer = dlq_writer
        self._on_attempt = on_attempt
        self._retryable = retryable_exceptions

    @property
    def dlq_writer(self) -> DLQWriter | None:
        """Public accessor для тестов / observability."""
        return self._dlq_writer

    def _is_enabled(self) -> bool:
        """Проверка глобального feature-flag (default-OFF)."""
        return bool(feature_flags.rpa_resilience_wrapper_enabled)

    def _backoff(self, attempt: int) -> float:
        """Exponential backoff с jitter (attempt — 0-indexed)."""
        base = min(self.backoff_initial * (2**attempt), self.backoff_max)
        if self.jitter > 0:
            base *= 1 + random.uniform(-self.jitter, self.jitter)  # noqa: S311  # non-cryptographic use
        return max(0.0, base)

    async def call(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        *,
        transport: str,
        tenant_id: str | None = None,
        route_id: str | None = None,
        payload: Any = None,
        on_error_reason: DLQReason = DLQReason.RETRIES_EXHAUSTED,
    ) -> T:
        """Выполняет coroutine factory с retry + breaker + DLQ.

        Args:
            coro_factory: callable, возвращающий awaitable (для retry — новый
                awaitable на каждой попытке, нельзя re-await consumed coroutine).
            transport: имя транспорта (browser_pool / cdc / file_watcher /
                webhook / desktop_rpa).
            tenant_id: tenant scope (опц.).
            route_id: DSL route id (опц.).
            payload: original payload для DLQ-envelope (replay).
            on_error_reason: DLQReason при exhausted retries.

        Returns:
            Результат успешного coro.

        Raises:
            RPACallExhausted: все попытки исчерпаны.
            ValueError: при breaker_open (если CB активен).
        """
        if not self._is_enabled():
            return await coro_factory()

        if self._breaker is not None and self._breaker.is_open():
            _logger.warning(
                "RPACallPolicy[%s] breaker_open transport=%s — skip",
                self.name,
                transport,
            )
            raise RPACallExhausted(
                transport, last_error=RuntimeError("circuit breaker open")
            )

        ctx = RPACallContext(
            transport=transport, tenant_id=tenant_id, route_id=route_id, payload=payload
        )
        _ = time.monotonic()

        for attempt in range(self.max_attempts):
            ctx.attempts = attempt + 1
            try:
                result = await coro_factory()
            except BaseException as exc:
                ctx.last_error = exc
                now = time.monotonic()
                if ctx.first_failed_at_ts is None:
                    ctx.first_failed_at_ts = now
                ctx.last_failed_at_ts = now

                if self._on_attempt is not None:
                    try:
                        self._on_attempt(ctx, attempt, exc)
                    except Exception as _:
                        _logger.exception("RPACallPolicy on_attempt callback failed")

                if self._breaker is not None:
                    self._breaker.on_failure()

                # Если исключение не в retryable — fail-fast (без retry, в DLQ).
                if not isinstance(exc, self._retryable):
                    await self._send_to_dlq(ctx, on_error_reason)
                    raise RPACallExhausted(transport, exc) from exc

                # Последняя попытка — отправить в DLQ + RPACallExhausted
                if attempt + 1 >= self.max_attempts:
                    await self._send_to_dlq(ctx, on_error_reason)
                    raise RPACallExhausted(transport, exc) from exc

                # Sleep перед следующей попыткой
                await asyncio.sleep(self._backoff(attempt))
                continue
            else:
                if self._breaker is not None:
                    self._breaker.on_success()
                if self._on_attempt is not None:
                    try:
                        self._on_attempt(ctx, attempt, None)
                    except Exception as _:
                        _logger.exception("RPACallPolicy on_attempt success cb failed")
                return result

        # unreachable (всегда return или raise внутри loop), но mypy doesn't know
        raise RPACallExhausted(
            transport, ctx.last_error or RuntimeError("RPACallPolicy unreachable")
        )

    async def _send_to_dlq(self, ctx: RPACallContext, reason: DLQReason) -> None:
        """Записывает envelope в DLQ (если writer настроен)."""
        if self._dlq_writer is None:
            return
        from datetime import datetime

        first_ts = (
            datetime.fromtimestamp(ctx.first_failed_at_ts, tz=UTC)
            if ctx.first_failed_at_ts
            else datetime.now(UTC)
        )
        last_ts = (
            datetime.fromtimestamp(ctx.last_failed_at_ts, tz=UTC)
            if ctx.last_failed_at_ts
            else datetime.now(UTC)
        )
        envelope = DLQEnvelope(
            transport=ctx.transport,
            tenant_id=ctx.tenant_id,
            route_id=ctx.route_id,
            original_payload=ctx.payload,
            error_class=type(ctx.last_error).__name__ if ctx.last_error else "Unknown",
            error_message=str(ctx.last_error) if ctx.last_error else "",
            reason=reason,
            retry_count=ctx.attempts,
            first_failed_at=first_ts,
            last_failed_at=last_ts,
            metadata={"policy": self.name},
        )
        try:
            await self._dlq_writer.write(envelope)
        except Exception as _:
            _logger.exception(
                "RPACallPolicy[%s] DLQ write failed transport=%s",
                self.name,
                ctx.transport,
            )


# Module-level singleton (опционально устанавливается на startup)
_default_policy: RPACallPolicy | None = None


def get_rpa_policy() -> RPACallPolicy | None:
    """Возвращает дефолтную RPACallPolicy (если установлена)."""
    return _default_policy


def set_rpa_policy(policy: RPACallPolicy | None) -> None:
    """Устанавливает дефолтную RPACallPolicy (вызывается в lifespan)."""
    global _default_policy
    _default_policy = policy
