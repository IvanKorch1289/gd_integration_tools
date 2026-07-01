"""Content-Based Router, Message Filter, Sampling EIP processors (S55 W2).

Apache Camel references:
- Content-Based Router: https://camel.apache.org/components/latest/eips/contentBasedRouter.html
- Message Filter: https://camel.apache.org/components/latest/eips/filter.html
- Sampling: https://camel.apache.org/components/latest/eips/sampling.html

Content-Based Router: routes message к one of N endpoints based on predicate.
Отличие от DynamicRouter: статический набор routes, выбор по predicate
(а не runtime-вычисление next route_id).

Message Filter: пропускает только messages, удовлетворяющие predicate;
остальные drop'аются (с optional sink для отброшенных).

Sampling: probabilistic subset — пропускает каждый N-й message (1/N rate)
или fraction-based (e.g., 10% of messages). Полезно для sampling production
traffic в test environment или для метрик.
"""

from __future__ import annotations

import random
import threading
from collections.abc import Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = ("ContentBasedRouter", "SamplingProcessor")

_log = get_logger(__name__)


# Type aliases
Predicate = Callable[[Exchange[Any]], bool]
RouteResolver = Callable[[Exchange[Any]], str | None]


# ── Content-Based Router ─────────────────────────────────────────────


class ContentBasedRouter(BaseProcessor):
    """Routes message к one из N endpoints based on predicates.

    Список ``routes`` — упорядоченные ``(predicate, endpoint)`` пары.
    First matching predicate wins (как в Camel). Если ни один не match:
    * ``default_endpoint`` если задан → route туда
    * иначе → message drop (но logging WARNING)

    Args:
        routes: list of (predicate, endpoint_name) tuples. Predicates
            evaluated в порядке списка. endpoint_name — str ID для
            downstream processor (e.g., для invoke_workflow / route_id).
        default_endpoint: fallback endpoint если ни один predicate не match.
        name: имя процессора.

    Пример::

        ContentBasedRouter(routes=[
            (lambda ex: ex.in_message.body.get("priority") == "high", "high_priority_route"),
            (lambda ex: ex.in_message.body.get("country") == "ru", "ru_route"),
        ], default_endpoint="default_route")
    """

    def __init__(
        self,
        routes: list[tuple[Predicate, str]],
        *,
        default_endpoint: str | None = None,
        name: str | None = None,
    ) -> None:
        if not routes:
            raise ValueError("ContentBasedRouter requires at least one route")
        super().__init__(name=name or "content_based_router")
        self._routes = routes
        self._default_endpoint = default_endpoint

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Маршрутизирует exchange по первому matched predicate."""
        for idx, (predicate, endpoint) in enumerate(self._routes):
            try:
                if predicate(exchange):
                    _log.debug(
                        "ContentBasedRouter: matched route %d → %s", idx, endpoint
                    )
                    exchange.set_property("routing.choice.endpoint", endpoint)
                    exchange.set_property("routing.choice.index", idx)
                    return
            except Exception as e:
                _log.warning("ContentBasedRouter: predicate %d raised: %s", idx, e)
                continue

        # No match
        if self._default_endpoint is not None:
            _log.debug(
                "ContentBasedRouter: no match, using default → %s",
                self._default_endpoint,
            )
            exchange.set_property("routing.choice.endpoint", self._default_endpoint)
            exchange.set_property("routing.choice.index", -1)
        else:
            _log.warning("ContentBasedRouter: no match, no default — message dropped")
            exchange.set_property("routing.choice.endpoint", None)
            exchange.set_property("routing.choice.dropped", True)
            exchange.stop()

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "content_based_router",
            "routes": len(self._routes),
            "default_endpoint": self._default_endpoint,
        }


# Message Filter — НЕ дублируем: существующий FilterProcessor в core.py
# покрывает use case (predicate + exchange.stop on no-match). Для programmatic
# использования — импортируйте из core.py.
# (С55 W6 dedup: MessageFilter class удалён; см. core.py::FilterProcessor)


# ── Sampling ────────────────────────────────────────────────────────


class SamplingProcessor(BaseProcessor):
    """Probabilistic subset: пропускает N-ую часть messages.

    Режимы:
    * ``rate`` (int) — pass-through 1 из N messages (e.g., rate=10 → 10%).
    * ``fraction`` (float 0-1) — pass-through given fraction.
    * ``time_window_ms`` + ``max_in_window`` — token-bucket sampling
      (e.g., max 5 messages per 1000ms).

    Dropped messages: exchange.sampled_out = True + exchange.stop().

    Args:
        rate: pass 1/rate messages (mutually exclusive с fraction).
        fraction: pass given fraction of messages (0.0-1.0).
        seed: random seed для reproducibility (default None).
        name: имя процессора.

    Пример::

        # 10% sampling
        SamplingProcessor(fraction=0.1)

        # Каждый 100-й
        SamplingProcessor(rate=100)

        # 5 per second
        SamplingProcessor(time_window_ms=1000, max_in_window=5)
    """

    def __init__(
        self,
        *,
        rate: int | None = None,
        fraction: float | None = None,
        time_window_ms: int | None = None,
        max_in_window: int | None = None,
        seed: int | None = None,
        name: str | None = None,
    ) -> None:
        if rate is not None and fraction is not None:
            raise ValueError("Specify either rate OR fraction, not both")
        if rate is None and fraction is None and time_window_ms is None:
            raise ValueError("Specify rate, fraction, or time_window_ms+max_in_window")
        if rate is not None and rate < 1:
            raise ValueError("rate must be >= 1")
        if fraction is not None and not 0.0 <= fraction <= 1.0:
            raise ValueError("fraction must be in [0.0, 1.0]")

        super().__init__(name=name or "sampling")
        self._rate = rate
        self._fraction = fraction
        self._time_window_ms = time_window_ms
        self._max_in_window = max_in_window
        # SECURITY: random.Random — non-cryptographic, fine для sampling/test filtering
        # (не используется для security tokens, IDs, или auth).
        self._rng = random.Random(seed)  # noqa: S311
        self._counter = 0
        self._window_start_ms: float = 0.0
        self._window_count = 0
        self._lock = threading.Lock()

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        passed = self._should_pass()
        exchange.set_property("sampling.passed", passed)
        if not passed:
            _log.debug("Sampling: message dropped (sampled out)")
            exchange.set_property("sampling.sampled_out", True)
            exchange.stop()

    def _should_pass(self) -> bool:
        if self._rate is not None:
            with self._lock:
                self._counter += 1
                return self._counter % self._rate == 0
        if self._fraction is not None:
            return self._rng.random() < self._fraction
        # Token-bucket by time window
        import time

        now_ms = time.monotonic() * 1000.0
        with self._lock:
            if now_ms - self._window_start_ms >= (self._time_window_ms or 0):
                self._window_start_ms = now_ms
                self._window_count = 0
            if self._window_count >= (self._max_in_window or 0):
                return False
            self._window_count += 1
            return True

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"type": "sampling"}
        if self._rate is not None:
            spec["rate"] = self._rate
        if self._fraction is not None:
            spec["fraction"] = self._fraction
        if self._time_window_ms is not None:
            spec["time_window_ms"] = self._time_window_ms
            spec["max_in_window"] = self._max_in_window
        return spec
