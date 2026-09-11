"""Route Simulator — dry-run route execution (Wave 1 P0 #26).

``RouteSimulator`` выполняет route contract с mocked I/O:

- Все external calls идут через ``MockConnector`` instances.
- Возвращается ``SimulationResult`` с output + recorded_calls + execution_log.

Используется для:
- Локальной разработки (без real side effects).
- CI contract tests (детерминированный output).
- Демо / sandbox mode.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from src.backend.core.route_simulation.mock import MockConnector, RecordedCall

logger = logging.getLogger(__name__)

__all__ = (
    "RouteSimulator",
    "SimulationResult",
    "SimulationStep",
    "get_route_simulator",
)


@dataclass(slots=True)
class SimulationStep:
    """Один шаг simulation."""

    name: str
    connector: str | None = None
    method: str | None = None
    args: dict[str, Any] = field(default_factory=dict)
    result: Any = None
    duration_ms: float = 0.0


@dataclass(slots=True)
class SimulationResult:
    """Результат route simulation."""

    contract_route_id: str
    output: dict[str, Any] = field(default_factory=dict)
    recorded_calls: list[RecordedCall] = field(default_factory=list)
    execution_log: list[SimulationStep] = field(default_factory=list)
    success: bool = True
    error: str | None = None
    total_duration_ms: float = 0.0


# Simulation step signature:
# ``async def step(payload, context) -> dict``.
SimStepFn = Callable[[dict[str, Any], dict[str, Any]], Any]


class RouteSimulator:
    """Dry-run simulator для route contracts.

    Использует словарь MockConnector'ов для external dependencies.
    Шаги задаются как список ``SimStepFn`` или регистрируются через decorator.
    """

    def __init__(
        self,
        *,
        connectors: dict[str, MockConnector] | None = None,
    ) -> None:
        self._connectors: dict[str, MockConnector] = connectors or {}
        # Steps: list of (name, callable).
        self._steps: list[tuple[str, SimStepFn]] = []

    def register_connector(self, name: str, connector: MockConnector) -> None:
        """Register mock connector."""
        self._connectors[name] = connector

    def get_connector(self, name: str) -> MockConnector | None:
        return self._connectors.get(name)

    def add_step(self, name: str, step_fn: SimStepFn) -> None:
        """Add simulation step."""
        self._steps.append((name, step_fn))

    def clear_steps(self) -> None:
        """Очистить steps."""
        self._steps.clear()

    def reset_mocks(self) -> None:
        """Reset все mock connectors."""
        for c in self._connectors.values():
            c.reset()

    def simulate(
        self,
        contract_route_id: str,
        payload: dict[str, Any] | None = None,
    ) -> SimulationResult:
        """Запустить simulation.

        Args:
            contract_route_id: ID маршрута (для traceability).
            payload: Input payload.

        Returns:
            :class:`SimulationResult` с output + recorded_calls + log.

        """
        start = time.time()
        payload = payload or {}
        result = SimulationResult(contract_route_id=contract_route_id)
        context: dict[str, Any] = {
            "connectors": self._connectors,
            "result": result,  # mutating result.execution_log
        }

        try:
            current_payload = dict(payload)
            for name, step_fn in self._steps:
                step_start = time.time()
                try:
                    step_result = step_fn(current_payload, context)
                except Exception as exc:
                    result.success = False
                    result.error = f"step {name!r} failed: {exc}"
                    logger.warning(
                        "Simulation: step %s failed: %s", name, exc
                    )
                    break
                # If step returns dict, merge into current payload (replace keys).
                if isinstance(step_result, dict):
                    current_payload.update(step_result)
                    result.output.update(step_result)
                else:
                    # Non-dict return → store as "output".
                    result.output["result"] = step_result
                step_duration = (time.time() - step_start) * 1000
                result.execution_log.append(
                    SimulationStep(
                        name=name,
                        result=step_result,
                        duration_ms=step_duration,
                    )
                )
        finally:
            # Collect recorded calls from all connectors.
            for c in self._connectors.values():
                result.recorded_calls.extend(c.calls)
            result.total_duration_ms = (time.time() - start) * 1000

        return result


_simulator: RouteSimulator | None = None


def get_route_simulator() -> RouteSimulator:
    global _simulator
    if _simulator is None:
        _simulator = RouteSimulator()
    return _simulator


def reset_route_simulator() -> None:
    global _simulator
    _simulator = None
