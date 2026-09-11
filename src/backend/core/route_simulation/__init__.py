"""Route Simulation / Dry-Run mode (Wave 1 P0 #26).

Проблема (EP-R1):
    При разработке нового route или изменении существующего нельзя
    безопасно проверить логику без реальных side effects:
    - writes в production DB;
    - payments / external calls;
    - файловые операции.

Решение:
    ``RouteSimulator`` — выполняет route graph с mocked I/O:

    1. ``simulate(contract, payload)`` → ``SimulationResult``:
       - Все external calls записываются в ``recorded_calls``.
       - Все writes идут в in-memory store (без commit).
       - Возвращается детерминированный result.

    2. ``MockConnector`` — base для моков external систем:
       - ``get_state()`` — записанные вызовы.
       - ``reset()`` — очистка.

    3. ``SimulationResult``:
       - output payload.
       - recorded_calls (list).
       - recorded_writes (list).
       - execution_log (step-by-step trace).

Использование::

    from src.backend.core.route_simulation import (
        RouteSimulator, MockConnector,
    )

    mock_db = MockConnector(name="db")
    simulator = RouteSimulator(connectors={"db": mock_db})

    result = simulator.simulate(contract, payload={"order_id": "o1"})
    assert result.output["status"] == "ok"
    assert len(mock_db.calls) == 1
"""

from __future__ import annotations

from src.backend.core.route_simulation.mock import (
    MockConnector,
    RecordedCall,
)
from src.backend.core.route_simulation.simulator import (
    RouteSimulator,
    SimulationResult,
    SimulationStep,
    get_route_simulator,
)

__all__ = (
    "MockConnector",
    "RecordedCall",
    "RouteSimulator",
    "SimulationResult",
    "SimulationStep",
    "get_route_simulator",
)
