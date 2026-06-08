"""Airflow-style operators для workflow branching/conditioning (S56 W2).

Apache Airflow operator catalog (https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html):

* :class:`BranchPythonOperator` — Python callable возвращает task_id для follow-up.
* :class:`ShortCircuitOperator` — skip downstream если predicate returns False.
* :class:`LatestOnlyOperator` — пропускает task если это не latest DAG run.
* :class:`BranchDateTimeOperator` — branch на основе date/time condition.
* :class:`ExternalTaskSensor` — ждёт завершения task в другом DAG.

В gd_integration_tools все operators — :class:`BaseProcessor` для inline-использования
в DSL-routes. Результат выбора branch записывается в ``exchange.set_property(...)``
— engine читает через :class:`BranchSelector`.

Использование в DSL::

    from src.backend.dsl.engine.processors.orchestration.airflow_operators import (
        BranchPythonOperator,
        ShortCircuitOperator,
        LatestOnlyOperator,
        BranchDateTimeOperator,
        ExternalTaskSensor,
        BRANCH_DECISION_PROPERTY,
    )

    route = (
        RouteBuilder()
        .from_interval("hourly_job", interval_s=3600)
        .process(BranchPythonOperator(
            python_callable=lambda ex: "process_a" if ex.in_message.body["count"] > 100 else "process_b",
        ))
        .process(ShortCircuitOperator(predicate=lambda ex: ex.in_message.body.get("enabled", False)))
    )

Thread-safe: branch decisions изолированы per-exchange (через ``set_property``);
``_LatestOnlyOperator`` использует lock для shared latest_run_id.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.infrastructure.logging.factory import get_logger

__all__ = (
    "BRANCH_DECISION_PROPERTY",
    "BRANCH_SKIP_VALUE",
    "BranchDateTimeOperator",
    "BranchPythonOperator",
    "BranchSelector",
    "ExternalTaskSensor",
    "LatestOnlyOperator",
    "ShortCircuitOperator",
)

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]


# ── BranchPythonOperator ─────────────────────────────────────────────


class BranchPythonOperator(BaseProcessor):
    """Python callable возвращает имя следующей task/branch.

    Apache Airflow BranchPythonOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#branchpythonoperator

    Args:
        python_callable: Callable, возвращающий ``str`` (task_id для follow-up)
            или :data:`BRANCH_SKIP_VALUE` если downstream нужно skip.
        allowed_branches: optional whitelist — если callable вернёт имя не из
            списка — error (для safety, default None = no restriction).
        name: имя процессора.

    Side effect: ``exchange.set_property(BRANCH_DECISION_PROPERTY, branch_name)``.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        python_callable: BranchResolver,
        *,
        allowed_branches: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        if python_callable is None:
            raise ValueError("BranchPythonOperator: python_callable is required")
        super().__init__(name=name or "branch_python")
        self._callable = python_callable
        self._allowed = allowed_branches

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        decision = self._callable(exchange)
        if asyncio.iscoroutine(decision):
            decision = await decision
        decision_str = str(decision)

        if self._allowed is not None and decision_str not in self._allowed:
            raise ValueError(
                f"BranchPythonOperator: returned {decision_str!r}, "
                f"not in allowed_branches={self._allowed}"
            )

        exchange.set_property(BRANCH_DECISION_PROPERTY, decision_str)
        _log.debug("BranchPythonOperator: decision=%s", decision_str)

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "branch_python", "allowed_branches": self._allowed}


# ── ShortCircuitOperator ────────────────────────────────────────────


class ShortCircuitOperator(BaseProcessor):
    """Skip downstream tasks если predicate returns ``False``.

    Apache Airflow ShortCircuitOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#shortcircuitoperator

    Args:
        predicate: Callable → bool. False = skip (write ``BRANCH_SKIP_VALUE``
            в property + ``exchange.skip_downstream()``).
        ignore_downstream_trigger_rules: если True — skip applies даже
            если downstream tasks имеют ``trigger_rule=always``. Default False.
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        predicate: Predicate,
        *,
        ignore_downstream_trigger_rules: bool = False,
        name: str | None = None,
    ) -> None:
        if predicate is None:
            raise ValueError("ShortCircuitOperator: predicate is required")
        super().__init__(name=name or "short_circuit")
        self._predicate = predicate
        self._ignore_trigger_rules = ignore_downstream_trigger_rules

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        result = self._predicate(exchange)
        if asyncio.iscoroutine(result):
            result = await result

        if result:
            _log.debug("ShortCircuitOperator: predicate=True, continue")
            # No decision property set — engine treats as "proceed normally"
            return

        _log.debug("ShortCircuitOperator: predicate=False, skip downstream")
        exchange.set_property(BRANCH_DECISION_PROPERTY, BRANCH_SKIP_VALUE)
        if self._ignore_trigger_rules:
            exchange.set_property("short_circuit.force_skip", True)
        exchange.stop()  # short-circuit: stop further processing in current route

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "short_circuit",
            "ignore_downstream_trigger_rules": self._ignore_trigger_rules,
        }


# ── LatestOnlyOperator ──────────────────────────────────────────────


class LatestOnlyOperator(BaseProcessor):
    """Skip task если текущий run — не latest в DAG.

    Apache Airflow LatestOnlyOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#latestonlyoperator

    Полезен для backfill: при запуске historical runs (backfill mode) часто
    нужно skip промежуточные tasks и оставить только latest.

    Args:
        latest_run_checker: callable(exchange) → bool. ``True`` если это
            latest run, ``False`` если старый. Если None — uses
            :meth:`_default_latest_checker` (checks ``is_latest_run`` header).
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self, latest_run_checker: Predicate | None = None, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or "latest_only")
        self._checker = latest_run_checker or _default_latest_checker

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        is_latest = self._checker(exchange)
        if asyncio.iscoroutine(is_latest):
            is_latest = await is_latest

        if is_latest:
            _log.debug("LatestOnlyOperator: this IS the latest run, proceed")
            return

        _log.debug("LatestOnlyOperator: NOT the latest run, skip downstream")
        exchange.set_property(BRANCH_DECISION_PROPERTY, BRANCH_SKIP_VALUE)
        exchange.set_property("latest_only.skipped", True)
        exchange.stop()

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "latest_only"}


def _default_latest_checker(exchange: Exchange[Any]) -> bool:
    """Default: check ``is_latest_run`` header (set by orchestrator)."""
    return bool(exchange.in_message.get_header("is_latest_run", default=True))


# ── BranchDateTimeOperator ──────────────────────────────────────────


class BranchDateTimeOperator(BaseProcessor):
    """Branch на основе date/time condition.

    Apache Airflow BranchDateTimeOperator: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/operators.html#branchdatetimeoperator

    Args:
        target_task_if_true: branch name если текущее время в target window.
        target_task_if_false: branch name если НЕ в window.
        target_lower: datetime — начало окна (inclusive). None = no lower bound.
        target_upper: datetime — конец окна (inclusive). None = no upper bound.
        use_task_execution_date: использовать ``execution_date`` из exchange
            headers (default True). Иначе ``datetime.now(UTC)``.
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(  # noqa: PLR0913
        self,
        target_task_if_true: str,
        target_task_if_false: str,
        *,
        target_lower: datetime | None = None,
        target_upper: datetime | None = None,
        use_task_execution_date: bool = True,
        name: str | None = None,
    ) -> None:
        if target_lower is not None and target_upper is not None:
            if target_lower > target_upper:
                raise ValueError("BranchDateTimeOperator: target_lower > target_upper")
        super().__init__(name=name or "branch_datetime")
        self._true_branch = target_task_if_true
        self._false_branch = target_task_if_false
        self._lower = target_lower
        self._upper = target_upper
        self._use_execution_date = use_task_execution_date

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        if self._use_execution_date:
            exec_date = exchange.in_message.get_header("execution_date")
            if isinstance(exec_date, datetime):
                now = exec_date
            else:
                now = datetime.now(tz=timezone.utc).replace(tzinfo=None)
        else:
            now = datetime.now(tz=timezone.utc).replace(tzinfo=None)

        in_window = True
        if self._lower is not None and now < self._lower:
            in_window = False
        if self._upper is not None and now > self._upper:
            in_window = False

        decision = self._true_branch if in_window else self._false_branch
        exchange.set_property(BRANCH_DECISION_PROPERTY, decision)
        _log.debug(
            "BranchDateTimeOperator: now=%s in_window=%s → %s",
            now.isoformat(),
            in_window,
            decision,
        )

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "branch_datetime",
            "true_branch": self._true_branch,
            "false_branch": self._false_branch,
            "lower": self._lower.isoformat() if self._lower else None,
            "upper": self._upper.isoformat() if self._upper else None,
        }


# ── ExternalTaskSensor ──────────────────────────────────────────────


class ExternalTaskSensor(BaseProcessor):
    """Ждёт завершения task в другом DAG / route (Airflow ExternalTaskSensor).

    Apache Airflow ExternalTaskSensor: https://airflow.apache.org/docs/apache-airflow/stable/core-concepts/sensors.html#externaltasksensor

    Args:
        external_dag_id: ID внешнего DAG/route.
        external_task_id: ID task во внешнем DAG. None = ждать завершения всего DAG.
        allowed_states: set состояний которые считаются "success" (default {"success"}).
        failed_states: set состояний которые считаются "failure" (default {"failed"}).
        check_fn: optional callable(exchange, state) → bool. Если вернёт False —
            retry. Default = state in allowed_states.
        poll_interval_s: интервал между проверками (default 5.0).
        timeout_s: max wait time, None = бесконечно.
        task_state_getter: callable(external_dag_id, external_task_id, execution_date)
            → str (state). Default — error (должен быть передан).
        name: имя процессора.
    """

    side_effect: ClassVar[SideEffectKind] = (
        SideEffectKind.PURE
    )  # sensor = pure observation

    def __init__(  # noqa: PLR0913
        self,
        external_dag_id: str,
        *,
        external_task_id: str | None = None,
        allowed_states: set[str] | None = None,
        failed_states: set[str] | None = None,
        check_fn: Callable[[Exchange[Any], str], bool] | None = None,
        poll_interval_s: float = 5.0,
        timeout_s: float | None = None,
        task_state_getter: Callable[[str, str | None, Any], str] | None = None,
        name: str | None = None,
    ) -> None:
        if not external_dag_id:
            raise ValueError("ExternalTaskSensor: external_dag_id is required")
        if task_state_getter is None:
            raise ValueError(
                "ExternalTaskSensor: task_state_getter is required "
                "(no default implementation; depends on orchestrator backend)"
            )
        super().__init__(name=name or "external_task_sensor")
        self._dag_id = external_dag_id
        self._task_id = external_task_id
        self._allowed = allowed_states or {"success"}
        self._failed = failed_states or {"failed"}
        self._check_fn = check_fn
        self._poll_interval_s = poll_interval_s
        self._timeout_s = timeout_s
        self._getter = task_state_getter
        self._lock = threading.Lock()
        self._polls = 0
        self._matches = 0
        self._timeouts = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        execution_date = exchange.in_message.get_header("execution_date")
        import time

        deadline = (time.monotonic() + self._timeout_s) if self._timeout_s else None
        current_state: str | None = None

        while True:
            with self._lock:
                self._polls += 1
            try:
                current_state = self._getter(
                    self._dag_id, self._task_id, execution_date
                )
            except Exception as exc:  # noqa: BLE001
                _log.warning(
                    "ExternalTaskSensor: state getter raised %s (dag=%s, task=%s)",
                    exc,
                    self._dag_id,
                    self._task_id,
                )
                if deadline and time.monotonic() >= deadline:
                    with self._lock:
                        self._timeouts += 1
                    raise TimeoutError(
                        f"ExternalTaskSensor: state getter failed for {self._dag_id}/{self._task_id}"
                    ) from exc
                await asyncio.sleep(self._poll_interval_s)
                continue

            if self._check_fn is not None:
                ok = self._check_fn(exchange, current_state)
                if asyncio.iscoroutine(ok):
                    ok = await ok
                if ok:
                    with self._lock:
                        self._matches += 1
                    exchange.set_property(
                        "external_task_sensor.last_state", current_state
                    )
                    return
            elif current_state in self._allowed:
                with self._lock:
                    self._matches += 1
                exchange.set_property("external_task_sensor.last_state", current_state)
                return
            elif current_state in self._failed:
                raise RuntimeError(
                    f"ExternalTaskSensor: external task {self._dag_id}/{self._task_id} "
                    f"reached failed state: {current_state}"
                )

            if deadline and time.monotonic() >= deadline:
                with self._lock:
                    self._timeouts += 1
                raise TimeoutError(
                    f"ExternalTaskSensor: timeout after {self._timeout_s}s "
                    f"waiting for {self._dag_id}/{self._task_id} (last state={current_state})"
                )

            _log.debug(
                "ExternalTaskSensor: poll %d, state=%s, sleeping %.1fs",
                self._polls,
                current_state,
                self._poll_interval_s,
            )
            await asyncio.sleep(self._poll_interval_s)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {
                "polls": self._polls,
                "matches": self._matches,
                "timeouts": self._timeouts,
            }

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "external_task_sensor",
            "external_dag_id": self._dag_id,
            "external_task_id": self._task_id,
            "allowed_states": sorted(self._allowed),
            "failed_states": sorted(self._failed),
            "poll_interval_s": self._poll_interval_s,
            "timeout_s": self._timeout_s,
        }


# ── BranchSelector — utility для downstream consumers ────────────────


class BranchSelector:
    """Утилита для downstream-процессоров: получить branch decision.

    Использование::

        selector = BranchSelector(operator=branch_op)
        next_branch = selector.resolve(exchange)  # str | None
        if next_branch == BRANCH_SKIP_VALUE:
            return  # skip downstream
        # else: route к next_branch
    """

    __slots__ = ("_operator",)

    def __init__(self, operator: BaseProcessor | None = None) -> None:
        self._operator = operator

    def resolve(self, exchange: Exchange[Any]) -> str | None:
        """Возвращает branch decision или None если не установлен."""
        decision = exchange.get_property(BRANCH_DECISION_PROPERTY)
        return str(decision) if decision is not None else None

    def is_skip(self, exchange: Exchange[Any]) -> bool:
        return self.resolve(exchange) == BRANCH_SKIP_VALUE
