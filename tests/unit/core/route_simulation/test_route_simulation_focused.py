"""Focused tests for ``core.route_simulation`` (Wave 1 P0 #26)."""

from __future__ import annotations

import pytest

from src.backend.core.route_simulation import (
    MockConnector,
    RecordedCall,
    RouteSimulator,
    SimulationResult,
    SimulationStep,
    get_route_simulator,
)
from src.backend.core.route_simulation.simulator import reset_route_simulator


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_route_simulator()


class TestMockConnectorInit:
    def test_init_defaults(self) -> None:
        m = MockConnector(name="db")
        assert m.name == "db"
        assert m.calls == []
        assert m.call_count == 0

    def test_init_with_default_response(self) -> None:
        m = MockConnector(name="db", default_response={"ok": True})
        result = m.record("query", "SELECT 1")
        assert result == {"ok": True}


class TestMockConnectorRecord:
    def test_record_default_response(self) -> None:
        m = MockConnector(name="db")
        result = m.record("query", "SELECT 1")
        assert result is None
        assert m.call_count == 1

    def test_record_explicit_response(self) -> None:
        m = MockConnector(name="db")
        result = m.record("query", "SELECT 1", response={"rows": []})
        assert result == {"rows": []}

    def test_record_programmed_response(self) -> None:
        m = MockConnector(name="db")
        m.set_response("find_user", {"id": 1, "name": "Alice"})
        result = m.record("find_user", 1)
        assert result == {"id": 1, "name": "Alice"}

    def test_record_with_kwargs(self) -> None:
        m = MockConnector(name="db")
        m.record("query", "SELECT * FROM users", limit=10)
        assert m.calls[0].kwargs == {"limit": 10}
        assert m.calls[0].args == ("SELECT * FROM users",)

    def test_record_timestamp(self) -> None:
        m = MockConnector(name="db")
        before = m.record("x")  # timestamp 1
        assert m.calls[0].timestamp > 0


class TestMockConnectorSetResponse:
    def test_set_response_overrides(self) -> None:
        m = MockConnector(name="db", default_response="default")
        m.set_response("find_user", "user-data")
        assert m.record("find_user") == "user-data"
        assert m.record("other") == "default"


class TestMockConnectorReset:
    def test_reset(self) -> None:
        m = MockConnector(name="db")
        m.record("query")
        m.set_response("x", "y")
        m.reset()
        assert m.call_count == 0
        assert m.record("x") is None  # responses also cleared


class TestMockConnectorRepr:
    def test_repr(self) -> None:
        m = MockConnector(name="db")
        assert "db" in repr(m)
        assert "0" in repr(m)
        m.record("x")
        assert "1" in repr(m)


class TestRecordedCall:
    def test_defaults(self) -> None:
        c = RecordedCall(method="x")
        assert c.args == ()
        assert c.kwargs == {}
        assert c.response is None
        assert c.timestamp == 0.0


class TestSimulationResult:
    def test_defaults(self) -> None:
        r = SimulationResult(contract_route_id="r1")
        assert r.output == {}
        assert r.recorded_calls == []
        assert r.execution_log == []
        assert r.success is True
        assert r.error is None


class TestSimulationStep:
    def test_defaults(self) -> None:
        s = SimulationStep(name="step1")
        assert s.connector is None
        assert s.method is None
        assert s.args == {}
        assert s.result is None
        assert s.duration_ms == 0.0


class TestRouteSimulatorInit:
    def test_init_default(self) -> None:
        sim = RouteSimulator()
        assert sim._connectors == {}
        assert sim._steps == []

    def test_init_with_connectors(self) -> None:
        db = MockConnector(name="db")
        sim = RouteSimulator(connectors={"db": db})
        assert sim.get_connector("db") is db


class TestRegisterConnector:
    def test_register(self) -> None:
        sim = RouteSimulator()
        db = MockConnector(name="db")
        sim.register_connector("db", db)
        assert sim.get_connector("db") is db

    def test_get_missing(self) -> None:
        sim = RouteSimulator()
        assert sim.get_connector("missing") is None


class TestAddStep:
    def test_add_and_clear(self) -> None:
        sim = RouteSimulator()

        def step(payload, ctx):
            return {}

        sim.add_step("s1", step)
        assert len(sim._steps) == 1
        sim.clear_steps()
        assert len(sim._steps) == 0


class TestSimulateEmpty:
    def test_simulate_no_steps(self) -> None:
        sim = RouteSimulator()
        result = sim.simulate(contract_route_id="r1", payload={"x": 1})
        assert result.contract_route_id == "r1"
        assert result.success is True
        assert result.error is None
        assert result.execution_log == []


class TestSimulateSingleStep:
    def test_step_returns_dict(self) -> None:
        sim = RouteSimulator()

        def step(payload, ctx):
            return {"status": "ok", "id": payload.get("id")}

        sim.add_step("process", step)
        result = sim.simulate(contract_route_id="r1", payload={"id": "o1"})
        assert result.success is True
        assert result.output["status"] == "ok"
        assert result.output["id"] == "o1"
        assert len(result.execution_log) == 1
        assert result.execution_log[0].name == "process"

    def test_step_returns_non_dict(self) -> None:
        sim = RouteSimulator()

        def step(payload, ctx):
            return 42

        sim.add_step("counter", step)
        result = sim.simulate(contract_route_id="r1")
        assert result.output["result"] == 42


class TestSimulateMultiStep:
    def test_chained_steps(self) -> None:
        sim = RouteSimulator()

        def step1(payload, ctx):
            payload["enriched"] = True
            return {"enriched": True}

        def step2(payload, ctx):
            return {"status": "processed", "enriched": payload["enriched"]}

        sim.add_step("enrich", step1)
        sim.add_step("process", step2)
        result = sim.simulate(contract_route_id="r1", payload={"id": "o1"})
        assert result.output["status"] == "processed"
        assert result.output["enriched"] is True
        assert len(result.execution_log) == 2


class TestSimulateStepFailure:
    def test_step_exception_marks_failed(self) -> None:
        sim = RouteSimulator()

        def step(payload, ctx):
            raise ValueError("boom")

        sim.add_step("bad", step)
        result = sim.simulate(contract_route_id="r1")
        assert result.success is False
        assert "boom" in result.error
        assert "bad" in result.error

    def test_subsequent_steps_skipped_after_failure(self) -> None:
        sim = RouteSimulator()
        executed = []

        def step1(payload, ctx):
            executed.append("step1")
            raise ValueError("boom")

        def step2(payload, ctx):
            executed.append("step2")
            return {}

        sim.add_step("s1", step1)
        sim.add_step("s2", step2)
        result = sim.simulate(contract_route_id="r1")
        assert result.success is False
        assert executed == ["step1"]


class TestSimulateWithMock:
    def test_step_uses_mock_connector(self) -> None:
        db = MockConnector(name="db", default_response={"rows": [{"id": 1}]})
        sim = RouteSimulator(connectors={"db": db})

        def step(payload, ctx):
            db = ctx["connectors"]["db"]
            result = db.record("query", "SELECT * FROM users", response={"id": 1})
            return {"user": result}

        sim.add_step("fetch_user", step)
        result = sim.simulate(contract_route_id="r1")
        assert result.output["user"] == {"id": 1}
        assert db.call_count == 1
        assert len(result.recorded_calls) == 1
        assert result.recorded_calls[0].method == "query"


class TestResetMocks:
    def test_reset_clears_all(self) -> None:
        db = MockConnector(name="db")
        mq = MockConnector(name="mq")
        sim = RouteSimulator(connectors={"db": db, "mq": mq})
        db.record("x")
        mq.record("y")
        sim.reset_mocks()
        assert db.call_count == 0
        assert mq.call_count == 0


class TestSingleton:
    def test_singleton(self) -> None:
        s1 = get_route_simulator()
        s2 = get_route_simulator()
        assert s1 is s2

    def test_reset(self) -> None:
        s1 = get_route_simulator()
        reset_route_simulator()
        s2 = get_route_simulator()
        assert s1 is not s2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import route_simulation

        assert len(route_simulation.__all__) == 6


class TestRealisticExample:
    def test_full_order_route_simulation(self) -> None:
        """Realistic example: simulate order create route."""
        db = MockConnector(name="db", default_response={"ok": True})
        mq = MockConnector(name="mq", default_response={"published": True})
        sim = RouteSimulator(connectors={"db": db, "mq": mq})

        # Step 1: validate payload
        def validate(payload, ctx):
            if "order_id" not in payload:
                raise ValueError("missing order_id")
            return {"validated": True}

        # Step 2: write to DB (mocked)
        def write_db(payload, ctx):
            ctx["connectors"]["db"].record(
                "insert", "orders", payload, response={"row_id": 1}
            )
            return {"row_id": 1}

        # Step 3: publish event (mocked)
        def publish(payload, ctx):
            ctx["connectors"]["mq"].record(
                "publish", "events.orders", {"order_id": payload["order_id"]}
            )
            return {"event_published": True}

        sim.add_step("validate", validate)
        sim.add_step("write_db", write_db)
        sim.add_step("publish", publish)

        result = sim.simulate(
            contract_route_id="order-create", payload={"order_id": "o1", "amount": 100}
        )
        assert result.success is True
        assert result.output["validated"] is True
        assert result.output["row_id"] == 1
        assert result.output["event_published"] is True
        assert db.call_count == 1
        assert mq.call_count == 1
        assert len(result.execution_log) == 3
