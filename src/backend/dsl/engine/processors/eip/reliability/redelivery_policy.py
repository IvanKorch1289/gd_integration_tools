"""S175 Phase 2: RedeliveryPolicyProcessor (full implementation).

Camel EIP: https://camel.apache.org/components/latest/eips/redelivery.html
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)
from src.backend.dsl.engine.processors.eip.reliability._legacy import (
    HEADER_REDELIVERED,
    HEADER_REDELIVERY_COUNT,
    RedeliveryAttempt,
)

_log = get_logger(__name__)

__all__ = (
    "RedeliveryPolicyProcessor",
    "RedeliveryAttempt",
    "HEADER_REDELIVERED",
    "HEADER_REDELIVERY_COUNT",
)


# ── RedeliveryPolicyProcessor ───────────────────────────────────────


class RedeliveryPolicyProcessor(BaseProcessor):
    """Retry-with-backoff policy для failed message delivery (Camel Redelivery).

    Args:
        max_attempts: максимум retries (default 3).
        initial_delay_s: начальная задержка (default 1.0).
        backoff_multiplier: factor для exponential backoff (default 2.0).
        max_delay_s: cap на delay (default 60.0).
        redelivery_header: имя header для redelivery counter (default
            ``redelivery_count``).
        on_exhausted_action: куда dispatchить после N failed attempts
            (default "dlq").
        action_dispatcher: callable(action_name, exchange) → None/Awaitable.
            Если None — exchange.stop() после exhausted.
        name: имя процессора.

    Логика: на каждом exchange.process() инкрементирует redelivery_count
    в header. Если count <= max_attempts — delay + retry. Иначе — exhausted.

    Это meta-processor: не выполняет downstream pipeline, только
    обновляет headers + применяет delay/dispatch решения.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(  # noqa: PLR0913
        self,
        *,
        max_attempts: int = 3,
        initial_delay_s: float = 1.0,
        backoff_multiplier: float = 2.0,
        max_delay_s: float = 60.0,
        redelivery_header: str = HEADER_REDELIVERY_COUNT,
        on_exhausted_action: str = "dlq",
        action_dispatcher: Callable[[str, Exchange[Any]], Any | Awaitable[Any]]
        | None = None,
        name: str | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if initial_delay_s < 0:
            raise ValueError("initial_delay_s must be >= 0")
        if backoff_multiplier < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        super().__init__(name=name or "redelivery_policy")
        self._max_attempts = max_attempts
        self._initial_delay = initial_delay_s
        self._backoff = backoff_multiplier
        self._max_delay = max_delay_s
        self._header = redelivery_header
        self._on_exhausted = on_exhausted_action
        self._dispatcher = action_dispatcher
        self._lock = threading.Lock()
        self._retried = 0
        self._exhausted = 0

    def _compute_delay(self, attempt: int) -> float:
        """Exponential backoff с cap."""
        delay = self._initial_delay * (self._backoff ** (attempt - 1))
        return min(delay, self._max_delay)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Применяет redelivery policy: retry с backoff до max_attempts, затем DLQ."""
        attempt_raw = exchange.in_message.get_header(self._header)
        if attempt_raw is None:
            attempt = 1
            exchange.in_message.set_header(self._header, 1)
        else:
            try:
                attempt = int(attempt_raw) + 1
            except (TypeError, ValueError):
                attempt = 1
            exchange.in_message.set_header(self._header, attempt)

        exchange.in_message.set_header(HEADER_REDELIVERED, True)

        if attempt > self._max_attempts:
            _log.warning(
                "RedeliveryPolicy: exhausted after %d attempts, dispatch to %s",
                attempt - 1,
                self._on_exhausted,
            )
            with self._lock:
                self._exhausted += 1
            exchange.set_property("redelivery_policy.exhausted", True)
            if self._dispatcher is not None:
                result = self._dispatcher(self._on_exhausted, exchange)
                if asyncio.iscoroutine(result):
                    await result
            exchange.stop()
            return

        delay = self._compute_delay(attempt)
        exchange.set_property("redelivery_policy.next_delay_s", delay)
        exchange.set_property("redelivery_policy.attempt", attempt)
        with self._lock:
            self._retried += 1
        _log.debug(
            "RedeliveryPolicy: attempt=%d/%d, delay=%.2fs",
            attempt,
            self._max_attempts,
            delay,
        )
        # Optional: apply delay (only if > 0 and not in synchronous mode)
        if delay > 0:
            await asyncio.sleep(delay)

    def stats(self) -> dict[str, int]:
        """Возвращает счётчики retried/exhausted под lock."""
        with self._lock:
            return {"retried": self._retried, "exhausted": self._exhausted}

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует конфиг процессора в JSON-Schema spec."""
        return {
            "type": "redelivery_policy",
            "max_attempts": self._max_attempts,
            "initial_delay_s": self._initial_delay,
            "backoff_multiplier": self._backoff,
            "max_delay_s": self._max_delay,
        }
