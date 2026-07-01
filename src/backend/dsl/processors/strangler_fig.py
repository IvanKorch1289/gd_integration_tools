"""StranglerFigProcessor — Strangler Fig pattern (v21 §2.3, #3 of 3 P0 gaps).

Closes v21 gap #3: Strangler Fig. Zero-downtime миграция legacy systems:
place facade in front of monolith, route traffic incrementally (old + new),
rollback if new fails.

Паттерн (Martin Fowler [^256^]):

    Old monolith ──┐
                  ├──► StranglerFig ──► Facade response
    New system  ──┘
                  ↑
            traffic split % (e.g. 10% → new, 90% → old)

Use cases:
* Постепенная миграция legacy SOAP → modern REST
* Database migration: dual-write (old + new), read from one, switch gradually
* API version migration: v1 → v2 with traffic ramp
* Microservices extraction: monolith → microservice

Components:
* :class:`StranglerFigProcessor` — routes request → old или new (per traffic_split_pct)
* :class:`StranglerFigRollback` — manual rollback (force old for all traffic)
* :class:`StranglerFigStats` — counters (routed_to_old, routed_to_new, errors)
* :class:`MigrationMixin` — chainable ``.strangler_fig(...)`` в RouteBuilder
"""

from __future__ import annotations

import random
import threading
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = (
    "MigrationMixin",
    "RouteTarget",
    "StranglerFigProcessor",
    "StranglerFigRollback",
    "StranglerFigStats",
    "get_strangler_stats",
    "reset_strangler_stats",
)

_log = get_logger(__name__)


class RouteTarget(str, Enum):
    """Target system для routing."""

    OLD = "old"
    NEW = "new"


@dataclass(slots=True)
class StranglerFigStats:
    """Counters для Strangler Fig traffic.

    Attributes:
        routed_to_old: Count of requests routed to old system.
        routed_to_new: Count of requests routed to new system.
        old_errors: Errors from old system.
        new_errors: Errors from new system.
    """

    routed_to_old: int = 0
    routed_to_new: int = 0
    old_errors: int = 0
    new_errors: int = 0
    rollbacks_triggered: int = 0

    def record_route(self, target: RouteTarget) -> None:
        if target == RouteTarget.OLD:
            self.routed_to_old += 1
        else:
            self.routed_to_new += 1

    def record_error(self, target: RouteTarget) -> None:
        if target == RouteTarget.OLD:
            self.old_errors += 1
        else:
            self.new_errors += 1

    def total(self) -> int:
        return self.routed_to_old + self.routed_to_new

    def new_pct(self) -> float:
        """Current % трафика на new system (0.0-100.0)."""
        if self.total() == 0:
            return 0.0
        return 100.0 * self.routed_to_new / self.total()


# RouteHandler = async (body) -> result
RouteHandler = Callable[[Any], Awaitable[Any]]


class StranglerFigRollback:
    """Manual rollback: force all traffic → old system.

    Singleton state — set rollback() чтобы заблокировать new system при
    production incident. Reset() чтобы вернуть к normal traffic split.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rollback_active: bool = False
        self._reason: str = ""

    @property
    def is_active(self) -> bool:
        return self._rollback_active

    @property
    def reason(self) -> str:
        return self._reason

    def trigger(self, reason: str) -> None:
        """Activate rollback — all traffic → old system."""
        with self._lock:
            self._rollback_active = True
            self._reason = reason
        _log.warning("Strangler Fig rollback triggered: %s", reason)

    def reset(self) -> None:
        """Deactivate rollback — return to normal traffic split."""
        with self._lock:
            self._rollback_active = False
            self._reason = ""
        _log.info("Strangler Fig rollback reset — normal traffic restored")


# ── Module-level singletons (DI-friendly) ─────────────────────────────


_stats: StranglerFigStats | None = None
_stats_lock = threading.Lock()
_rollback = StranglerFigRollback()


def get_strangler_stats() -> StranglerFigStats:
    """Return module-level StranglerFigStats singleton."""
    global _stats
    if _stats is None:
        with _stats_lock:
            if _stats is None:
                _stats = StranglerFigStats()
    return _stats


def reset_strangler_stats() -> StranglerFigStats:
    """Reset stats (только для tests)."""
    global _stats
    with _stats_lock:
        _stats = StranglerFigStats()
    return _stats


def get_strangler_rollback() -> StranglerFigRollback:
    """Return module-level StranglerFigRollback singleton."""
    return _rollback


def reset_strangler_rollback() -> None:
    """Reset rollback state (только для tests)."""
    _rollback.reset()


# ── StranglerFigProcessor ──────────────────────────────────────────────


class StranglerFigProcessor(BaseProcessor):
    """Routes request → old или new system per traffic_split_pct.

    Args:
        old_handler: async (body) -> result для old system.
        new_handler: async (body) -> result для new system.
        traffic_split_pct: % трафика на new (0-100). 0 = all old, 100 = all new.
            Default 0 (= safe mode, no traffic to new).
        deterministic_seed: If set, use seeded random для deterministic routing
            (для tests / canary deployments).
        on_new_error: If True, error в new system → fallback to old. Default True.
        name: Processor name.

    Поведение:
    1. Check rollback state — if active, route to old (100%)
    2. Roll random или deterministic (per seed) — route to new if rand < split_pct
    3. Call handler, catch exception
    4. If error в new AND on_new_error=True → fallback to old, record error
    5. Update stats
    6. Store chosen target в exchange.properties['strangler_target']
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = True  # можно откатить (route to old)

    def __init__(
        self,
        *,
        old_handler: RouteHandler,
        new_handler: RouteHandler,
        traffic_split_pct: float = 0.0,
        deterministic_seed: int | None = None,
        on_new_error: bool = True,
        stats: StranglerFigStats | None = None,
        rollback: StranglerFigRollback | None = None,
        name: str | None = None,
    ) -> None:
        if not 0.0 <= traffic_split_pct <= 100.0:
            raise ValueError(
                f"traffic_split_pct должен быть 0-100, получено {traffic_split_pct}"
            )
        if old_handler is None or new_handler is None:
            raise ValueError("old_handler и new_handler обязательны")
        super().__init__(name=name or "strangler_fig")
        self._old_handler = old_handler
        self._new_handler = new_handler
        self._split_pct = traffic_split_pct
        self._on_new_error = on_new_error
        self._stats = stats or get_strangler_stats()
        self._rollback = rollback or get_strangler_rollback()
        self._seed = deterministic_seed
        # Per-instance random для deterministic routing
        # S311: random для traffic split, не crypto (комментарий явно)
        self._rng = (
            random.Random(deterministic_seed)  # noqa: S311
            if deterministic_seed is not None
            else None
        )  # noqa: S311

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Маршрутизирует запрос между старой и новой системами по traffic-split с fallback на старую при ошибке.

        Args:
            exchange: Текущий обмен с телом запроса.
            context: Контекст выполнения процессора.
        """
        body = exchange.in_message.body
        # 1. Check rollback
        if self._rollback.is_active:
            target = RouteTarget.OLD
        else:
            # 2. Roll
            roll_value = (
                self._rng.random() * 100.0
                if self._rng is not None
                else random.random() * 100.0  # noqa: S311
            )
            target = (
                RouteTarget.NEW if roll_value < self._split_pct else RouteTarget.OLD
            )  # noqa: S311

        # 3. Execute
        try:
            if target == RouteTarget.OLD:
                result = await self._old_handler(body)
            else:
                result = await self._new_handler(body)
            self._stats.record_route(target)
        except Exception as exc:  # noqa: BLE001
            self._stats.record_error(target)
            if target == RouteTarget.NEW and self._on_new_error:
                # Fallback to old
                _log.warning("new system failed (%s), falling back to old", exc)
                result = await self._old_handler(body)
                self._stats.record_route(RouteTarget.OLD)
                target = RouteTarget.OLD  # update for properties below
            else:
                raise

        # 4. Store target + result
        exchange.set_property("strangler_target", target.value)
        exchange.set_out(body=result, headers=dict(exchange.in_message.headers))

    def trigger_rollback(self, reason: str) -> None:
        """Manually trigger rollback (force all traffic → old)."""
        self._stats.rollbacks_triggered += 1
        self._rollback.trigger(reason)


# ── MigrationMixin ─────────────────────────────────────────────────────


class MigrationMixin:
    """Mixin для :class:`RouteBuilder` — chainable ``.strangler_fig(...)``.

    Stateless: ``self._add`` через MRO.
    """

    __slots__ = ()

    def strangler_fig(
        self,
        *,
        old_handler: RouteHandler,
        new_handler: RouteHandler,
        traffic_split_pct: float = 0.0,
        deterministic_seed: int | None = None,
        on_new_error: bool = True,
    ) -> "RouteBuilder":
        """Добавить :class:`StranglerFigProcessor` в pipeline.

        Args:
            old_handler: async (body) -> result для old system.
            new_handler: async (body) -> result для new system.
            traffic_split_pct: % трафика на new (0-100). 0 = safe mode.
            deterministic_seed: Seeded random для deterministic routing.
            on_new_error: Auto-fallback to old on new system error.
        """
        return self._add(  # type: ignore[attr-defined]
            StranglerFigProcessor(
                old_handler=old_handler,
                new_handler=new_handler,
                traffic_split_pct=traffic_split_pct,
                deterministic_seed=deterministic_seed,
                on_new_error=on_new_error,
            )
        )
