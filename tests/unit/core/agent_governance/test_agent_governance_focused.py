"""Focused tests for ``core.agent_governance`` (Wave 3 #18, #20)."""

from __future__ import annotations

import pytest

from src.backend.core.agent_governance import (
    ExecutionLedger,
    ExecutionRecord,
    ToolCapability,
    ToolPolicy,
    ToolPolicyEngine,
    get_execution_ledger,
    get_tool_policy_engine,
)
from src.backend.core.agent_governance.ledger import reset_execution_ledger
from src.backend.core.agent_governance.policy import reset_tool_policy_engine


@pytest.fixture(autouse=True)
def _reset() -> None:
    reset_tool_policy_engine()
    reset_execution_ledger()


class TestToolCapability:
    def test_values(self) -> None:
        assert ToolCapability.READ.value == "read"
        assert ToolCapability.WRITE.value == "write"
        assert ToolCapability.EXTERNAL.value == "external"
        assert ToolCapability.ADMIN.value == "admin"
        assert ToolCapability.SANDBOX.value == "sandbox"


class TestToolPolicy:
    def test_defaults(self) -> None:
        p = ToolPolicy(tool_name="db_read", capability=ToolCapability.READ)
        assert p.allowed_agents == []
        assert p.allowed_tenants == []
        assert p.requires_approval is False
        assert p.max_calls_per_minute == 0

    def test_full(self) -> None:
        p = ToolPolicy(
            tool_name="db_write",
            capability=ToolCapability.WRITE,
            allowed_agents=["alice", "bob"],
            allowed_tenants=["t1"],
            requires_approval=True,
            max_calls_per_minute=10,
        )
        assert p.requires_approval is True


class TestToolPolicyEngineInit:
    def test_init_empty(self) -> None:
        e = ToolPolicyEngine()
        assert e.get("missing") is None


class TestEngineRegister:
    def test_register(self) -> None:
        e = ToolPolicyEngine()
        e.register(ToolPolicy(tool_name="db_read", capability=ToolCapability.READ))
        assert e.get("db_read") is not None

    def test_register_overwrite(self) -> None:
        e = ToolPolicyEngine()
        e.register(ToolPolicy(tool_name="x", capability=ToolCapability.READ))
        e.register(ToolPolicy(tool_name="x", capability=ToolCapability.WRITE))
        assert e.get("x").capability == ToolCapability.WRITE


class TestEngineIsAllowed:
    def test_no_policy_deny(self) -> None:
        """No policy → deny by default (fail-closed)."""
        e = ToolPolicyEngine()
        assert e.is_allowed(tool="unknown") is False

    def test_allow_all_agents_and_tenants(self) -> None:
        e = ToolPolicyEngine()
        e.register(ToolPolicy(tool_name="x", capability=ToolCapability.READ))
        assert e.is_allowed(tool="x") is True
        assert e.is_allowed(tool="x", agent="alice") is True
        assert e.is_allowed(tool="x", tenant="t1") is True

    def test_allow_specific_agent(self) -> None:
        e = ToolPolicyEngine()
        e.register(
            ToolPolicy(
                tool_name="x",
                capability=ToolCapability.WRITE,
                allowed_agents=["alice"],
            )
        )
        assert e.is_allowed(tool="x", agent="alice") is True
        assert e.is_allowed(tool="x", agent="bob") is False

    def test_allow_specific_tenant(self) -> None:
        e = ToolPolicyEngine()
        e.register(
            ToolPolicy(
                tool_name="x",
                capability=ToolCapability.WRITE,
                allowed_tenants=["t1"],
            )
        )
        assert e.is_allowed(tool="x", tenant="t1") is True
        assert e.is_allowed(tool="x", tenant="t2") is False

    def test_combined_agent_and_tenant(self) -> None:
        e = ToolPolicyEngine()
        e.register(
            ToolPolicy(
                tool_name="x",
                capability=ToolCapability.WRITE,
                allowed_agents=["alice"],
                allowed_tenants=["t1"],
            )
        )
        # Both must match.
        assert e.is_allowed(tool="x", agent="alice", tenant="t1") is True
        assert e.is_allowed(tool="x", agent="alice", tenant="t2") is False
        assert e.is_allowed(tool="x", agent="bob", tenant="t1") is False


class TestEngineRequiresApproval:
    def test_requires_approval(self) -> None:
        e = ToolPolicyEngine()
        e.register(
            ToolPolicy(
                tool_name="db_write",
                capability=ToolCapability.WRITE,
                requires_approval=True,
            )
        )
        assert e.requires_approval("db_write") is True

    def test_no_policy_no_approval(self) -> None:
        e = ToolPolicyEngine()
        assert e.requires_approval("missing") is False


class TestEngineCapability:
    def test_capability_of(self) -> None:
        e = ToolPolicyEngine()
        e.register(
            ToolPolicy(tool_name="x", capability=ToolCapability.ADMIN)
        )
        assert e.capability_of("x") == ToolCapability.ADMIN

    def test_capability_missing(self) -> None:
        e = ToolPolicyEngine()
        assert e.capability_of("missing") is None


class TestExecutionRecord:
    def test_defaults(self) -> None:
        r = ExecutionRecord(
            execution_id="e1",
            agent="alice",
            tenant_id="t1",
            tool="db_read",
            arguments={},
        )
        assert r.result is None
        assert r.approved_by is None
        assert r.timestamp == 0.0
        assert r.status == "success"

    def test_to_dict(self) -> None:
        r = ExecutionRecord(
            execution_id="e1",
            agent="alice",
            tenant_id="t1",
            tool="db_write",
            arguments={"order_id": "o1"},
            result={"status": "ok"},
        )
        d = r.to_dict()
        assert d["execution_id"] == "e1"
        assert d["arguments"] == {"order_id": "o1"}


class TestExecutionLedgerInit:
    def test_init_empty(self) -> None:
        l = ExecutionLedger()
        assert l.size() == 0


class TestLedgerRecord:
    def test_record_basic(self) -> None:
        l = ExecutionLedger()
        rec = l.record(
            agent="alice",
            tenant_id="t1",
            tool="db_read",
            arguments={"table": "users"},
        )
        assert rec.execution_id
        assert rec.agent == "alice"
        assert rec.tenant_id == "t1"
        assert rec.tool == "db_read"
        assert rec.status == "success"
        assert l.size() == 1

    def test_record_with_approval(self) -> None:
        l = ExecutionLedger()
        rec = l.record(
            agent="alice",
            tenant_id="t1",
            tool="db_write",
            arguments={},
            approved_by="bob",
            approval_record_id="apr-1",
        )
        assert rec.approved_by == "bob"
        assert rec.approval_record_id == "apr-1"

    def test_record_with_error(self) -> None:
        l = ExecutionLedger()
        rec = l.record(
            agent="alice",
            tenant_id="t1",
            tool="db_write",
            arguments={},
            error="timeout",
            status="failed",
        )
        assert rec.status == "failed"
        assert rec.error == "timeout"


class TestLedgerList:
    def test_list_for_agent(self) -> None:
        l = ExecutionLedger()
        l.record(agent="alice", tenant_id="t1", tool="db_read", arguments={})
        l.record(agent="alice", tenant_id="t1", tool="db_write", arguments={})
        l.record(agent="bob", tenant_id="t1", tool="db_read", arguments={})
        alice_records = l.list_for_agent("alice")
        assert len(alice_records) == 2

    def test_list_for_tenant(self) -> None:
        l = ExecutionLedger()
        l.record(agent="a", tenant_id="t1", tool="x", arguments={})
        l.record(agent="b", tenant_id="t2", tool="x", arguments={})
        t1 = l.list_for_tenant("t1")
        assert len(t1) == 1

    def test_list_for_tool(self) -> None:
        l = ExecutionLedger()
        l.record(agent="a", tenant_id="t1", tool="db_read", arguments={})
        l.record(agent="a", tenant_id="t1", tool="db_write", arguments={})
        reads = l.list_for_tool("db_read")
        assert len(reads) == 1


class TestSingleton:
    def test_policy_singleton(self) -> None:
        e1 = get_tool_policy_engine()
        e2 = get_tool_policy_engine()
        assert e1 is e2

    def test_ledger_singleton(self) -> None:
        l1 = get_execution_ledger()
        l2 = get_execution_ledger()
        assert l1 is l2

    def test_reset(self) -> None:
        e1 = get_tool_policy_engine()
        l1 = get_execution_ledger()
        reset_tool_policy_engine()
        reset_execution_ledger()
        e2 = get_tool_policy_engine()
        l2 = get_execution_ledger()
        assert e1 is not e2
        assert l1 is not l2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import agent_governance

        assert len(agent_governance.__all__) == 7


class TestRealisticExample:
    def test_full_agent_governance_flow(self) -> None:
        """Realistic: agent tries to write, gets approved, ledger records it."""
        policy_engine = get_tool_policy_engine()
        policy_engine.register(
            ToolPolicy(
                tool_name="order_write",
                capability=ToolCapability.WRITE,
                allowed_agents=["alice"],
                allowed_tenants=["t1"],
                requires_approval=True,
            )
        )

        ledger = get_execution_ledger()

        # 1. Policy check.
        assert policy_engine.is_allowed(
            tool="order_write", agent="alice", tenant="t1"
        ) is True
        assert policy_engine.requires_approval("order_write") is True

        # 2. Approval gate (assume bob approves).
        approved = True
        if approved:
            # 3. Record execution.
            rec = ledger.record(
                agent="alice",
                tenant_id="t1",
                tool="order_write",
                arguments={"order_id": "o1", "amount": 100},
                result={"status": "created"},
                approved_by="bob",
                approval_record_id="apr-uuid",
                trace_id="trace-abc",
                duration_ms=42.0,
            )

        # 4. Audit query.
        alice_records = ledger.list_for_agent("alice")
        assert len(alice_records) == 1
        assert alice_records[0].approved_by == "bob"
        assert alice_records[0].trace_id == "trace-abc"
