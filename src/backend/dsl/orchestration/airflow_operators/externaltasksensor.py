from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

_log = get_logger(__name__)

# Property name для branch decision (consumed by BranchSelector / routing logic).
BRANCH_DECISION_PROPERTY = "branch.decision"
# Sentinel: operator решил "skip downstream" (no follow-up tasks).
BRANCH_SKIP_VALUE = "__skip__"

# Type alias: branch resolver returns task/branch name (or BRANCH_SKIP_VALUE).
BranchResolver = Callable[[Exchange[Any]], str | Awaitable[str]]
Predicate = Callable[[Exchange[Any]], bool | Awaitable[bool]]

# ── BranchPythonOperator ─────────────────────────────────────────────


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
