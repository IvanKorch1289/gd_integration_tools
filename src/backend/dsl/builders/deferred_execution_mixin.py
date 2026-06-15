"""DeferredExecutionMixin (S39 W5 — Airflow-style deferred scheduling).

Adds Apache-Airflow-style deferred execution primitives to
:class:`RouteBuilder` DSL:

* :meth:`DeferredExecutionMixin.defer_for` — defer by N seconds.
* :meth:`DeferredExecutionMixin.schedule` — defer via cron expression.
* :meth:`DeferredExecutionMixin.defer_until` — defer until specific time.
* :meth:`DeferredExecutionMixin.defer_if` — conditional defer (callable).
* :meth:`DeferredExecutionMixin.cancel_deferred` — cancel pending deferral.

Идиома (Camel-style, Airflow-inspired)::

    route = (
        RouteBuilder.from_("orders.cleanup", source="timer:300s")
        .defer_for(seconds=120)
        .dispatch_action("orders.cleanup")
        .build()
    )

Все методы — **chainable** (``return self``) и **NO-OP at builder-time**:
они лишь фиксируют intent в ``_deferred`` slot'е :class:`RouteBuilder`.
Реальное исполнение deferral'а происходит в runtime через
:mod:`src.backend.infrastructure.scheduler` (Temporal по умолчанию,
APScheduler fallback). Сейчас mixin задаёт контракт данных; runtime
интеграция — в отдельной wave.

Note:
    ``defer_for`` назван так, чтобы не конфликтовать с
    :meth:`ControlFlowMixin.delay` (runtime delay-процессор в
    pipeline). Семантика: ``defer_for(seconds=N)`` декларирует
    intent перенести исполнение, а не вставляет runtime-processor.

Контракт миксина:
    * stateless — нет instance-атрибутов;
    * ``__slots__ = ()`` — обязательно (см. ADR DSL Foundation Refactor);
    * не содержит ``@dataclass``;
    * state хранится в :class:`RouteBuilder._deferred` (dict).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Union

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder

__all__ = ("DeferredExecutionMixin",)

# Default delay: Airflow-style "execute after" timeout.
DEFAULT_DELAY_SECONDS: int = 60

# Cron-полей допустимо 5 (min hour dom mon dow) или 6 (sec min hour dom mon dow).
_CRON_FIELDS = (5, 6)

# Callable-сигнатура для defer_if: принимает ``Exchange`` (или dict-like)
# и возвращает bool.
DeferCondition = Callable[[Any], bool]

# Union для defer_until timestamp-аргумента.
TimestampLike = Union[datetime, str, int, float]


def _validate_cron_expression(expression: str) -> str:
    """Валидирует cron-выражение через :mod:`croniter`.

    Args:
        expression: 5- или 6-полевая cron-строка.

    Returns:
        Нормализованное выражение (stripped).

    Raises:
        ValueError: некорректное cron-выражение.
    """
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Cron expression must be a non-empty string")

    expr = expression.strip()
    fields = expr.split()
    if len(fields) not in _CRON_FIELDS:
        raise ValueError(
            f"Cron expression must have 5 or 6 fields, got {len(fields)}: {expr!r}"
        )

    # Lazy import — croniter project dep, но держим import границу узкой.
    from croniter import croniter

    # second_at_beginning=True для 6-полевого формата (sec min hour dom mon dow).
    try:
        croniter(expr, datetime.now(tz=UTC), second_at_beginning=len(fields) == 6)
    except (ValueError, KeyError) as exc:
        raise ValueError(f"Invalid cron expression {expr!r}: {exc}") from exc

    return expr


def _coerce_timestamp(value: TimestampLike) -> float:
    """Нормализует timestamp-like значение в unix-секунды (float, UTC).

    Поддерживает:
        * ``datetime`` — naive трактуется как UTC; aware конвертируется в UTC.
        * ``str`` — ISO-8601 (с/без timezone). Naive → UTC.
        * ``int``/``float`` — трактуется как unix timestamp.

    Args:
        value: timestamp-like значение.

    Returns:
        Unix-секунды (float).

    Raises:
        TypeError: ``value`` имеет неподдерживаемый тип.
        ValueError: строка не парсится как ISO-8601.
    """
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        else:
            value = value.astimezone(UTC)
        return value.timestamp()

    if isinstance(value, bool):
        # bool — подкласс int, но логически это не timestamp. Защита от путаницы.
        raise TypeError(f"defer_until: bool is not a valid timestamp, got {value!r}")

    if isinstance(value, (int, float)):
        return float(value)

    if isinstance(value, str):
        s = value.strip()
        if not s:
            raise ValueError("defer_until: empty string is not a valid timestamp")
        # ``datetime.fromisoformat`` (Python 3.11+) парсит ISO-8601 с timezone.
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as exc:
            raise ValueError(
                f"defer_until: cannot parse ISO-8601 string {value!r}: {exc}"
            ) from exc
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        else:
            dt = dt.astimezone(UTC)
        return dt.timestamp()

    raise TypeError(
        f"defer_until: unsupported type {type(value).__name__!r}; "
        "expected datetime, ISO-8601 string, int, or float"
    )


class DeferredExecutionMixin:
    """RouteBuilder mixin: Airflow-style defer primitives (delay/schedule/...)."""

    __slots__ = ()

    # ── Public API ──

    def defer_for(self, seconds: int = DEFAULT_DELAY_SECONDS) -> RouteBuilder:
        """Defer execution на ``seconds`` секунд (Airflow-style ``execution_date``).

        Args:
            seconds: Задержка в секундах. Default ``60``. Должен быть ≥ 0.

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            ValueError: ``seconds`` отрицательный.
            TypeError: ``seconds`` не int.
        """
        if not isinstance(seconds, int) or isinstance(seconds, bool):
            raise TypeError(
                f"defer_for: seconds must be int, got {type(seconds).__name__}"
            )
        if seconds < 0:
            raise ValueError(f"defer_for: seconds must be >= 0, got {seconds}")

        self._set_deferred(
            {"type": "delay", "seconds": seconds, "scheduled_at": time.time()}
        )
        return self  # type: ignore

    def schedule(self, *, cron: str, timezone_name: str = "UTC") -> RouteBuilder:
        """Defer execution по cron-расписанию (Airflow-style ``schedule_interval``).

        Cron-выражение валидируется через :mod:`croniter` (5- или 6-полевое).
        Поддерживаются 5 (``min hour dom mon dow``) и 6 (``sec min hour dom mon dow``)
        полей.

        Args:
            cron: cron-выражение, e.g. ``"0 * * * *"`` (каждый час) или
                ``"*/5 * * * *"`` (каждые 5 минут).
            timezone_name: IANA timezone для cron-evaluations. Default ``"UTC"``.

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            ValueError: невалидное cron-выражение.
        """
        expression = _validate_cron_expression(cron)
        self._set_deferred(
            {
                "type": "cron",
                "expression": expression,
                "timezone": timezone_name,
                "scheduled_at": time.time(),
            }
        )
        return self  # type: ignore

    def defer_until(self, timestamp: TimestampLike) -> RouteBuilder:
        """Defer execution до указанного момента (Airflow-style ``sla``).

        Args:
            timestamp: один из:
                * :class:`datetime.datetime` (naive → UTC; aware → convert to UTC);
                * ``str`` ISO-8601 (с/без timezone);
                * ``int``/``float`` unix timestamp (UTC).

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            TypeError: ``timestamp`` имеет неподдерживаемый тип.
            ValueError: ``str`` не парсится как ISO-8601.
        """
        ts = _coerce_timestamp(timestamp)
        self._set_deferred(
            {"type": "until", "timestamp": ts, "scheduled_at": time.time()}
        )
        return self  # type: ignore

    def defer_if(self, condition: DeferCondition) -> RouteBuilder:
        """Conditional defer — выполнить defer только если ``condition(exchange)`` truthy.

        Args:
            condition: callable, принимающий exchange и возвращающий bool.
                Вызывается в runtime, **не** at builder-time.

        Returns:
            ``RouteBuilder`` для chaining.

        Raises:
            TypeError: ``condition`` не callable.
        """
        if not callable(condition):
            raise TypeError(
                f"defer_if: condition must be callable, got {type(condition).__name__}"
            )
        self._set_deferred(
            {"type": "conditional", "condition": condition, "scheduled_at": time.time()}
        )
        return self  # type: ignore

    def cancel_deferred(self) -> RouteBuilder:
        """Отменить pending deferral (clear ``_deferred`` slot).

        Returns:
            ``RouteBuilder`` для chaining.

        Note:
            Идемпотентно: устанавливает ``_deferred`` в ``{}`` (создаёт slot
            если отсутствует). Это нужно для downstream-assert'ов вида
            ``assert builder._deferred == {}`` после ``cancel_deferred()``.
        """
        object.__setattr__(self, "_deferred", {})
        return self  # type: ignore

    # ── Internal helpers ──

    def _set_deferred(self, payload: dict[str, Any]) -> None:
        """Установить ``_deferred`` slot на builder (lazy init)."""
        # ``_deferred`` объявлен field(default_factory=dict) на RouteBuilder,
        # но при изолированных FakeBuilder-stub'ах может отсутствовать —
        # используем ``object.__setattr__`` для обхода ``@dataclass(slots=True)``.
        object.__setattr__(self, "_deferred", dict(payload))
