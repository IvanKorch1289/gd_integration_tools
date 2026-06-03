"""Unit tests for src.backend.core.ai.agent_spec."""

from __future__ import annotations

import pytest

from src.backend.core.ai.agent_spec import AgentSpec, HandoffPolicy, MemoryScope


class TestMemoryScope:
    def test_defaults(self) -> None:
        ms = MemoryScope()
        assert ms.read == ()
        assert ms.write == ()
        assert ms.mode == "scoped"
        assert ms.write_strategy == "background"

    def test_custom(self) -> None:
        ms = MemoryScope(
            read=("m1",), write=("m2",), mode="shared", write_strategy="hot_path"
        )
        assert ms.read == ("m1",)
        assert ms.write == ("m2",)
        assert ms.mode == "shared"
        assert ms.write_strategy == "hot_path"


class TestHandoffPolicy:
    def test_defaults(self) -> None:
        hp = HandoffPolicy()
        assert hp.max_handoffs == 5
        assert hp.allow_revisit is False
        assert hp.escalation_on_max_handoffs is None

    def test_custom(self) -> None:
        hp = HandoffPolicy(max_handoffs=3, allow_revisit=True, escalation_on_max_handoffs="admin")
        assert hp.max_handoffs == 3
        assert hp.allow_revisit is True
        assert hp.escalation_on_max_handoffs == "admin"


class TestAgentSpec:
    def test_minimal(self) -> None:
        spec = AgentSpec(id="a1", version="1.0.0", model="openai:gpt-4")
        assert spec.id == "a1"
        assert spec.version == "1.0.0"
        assert spec.model == "openai:gpt-4"
        assert spec.prompt_ref is None
        assert spec.skills == ()
        assert spec.tools == ()
        assert spec.memory == MemoryScope()
        assert spec.handoff == HandoffPolicy()
        assert spec.policy_ref is None
        assert spec.max_turns == 10
        assert spec.timeout_s == 60.0
        assert spec.tenant_aware is True
        assert spec.feature_flag is None

    def test_full(self) -> None:
        spec = AgentSpec(
            id="a2",
            version="2.0.0",
            model="minimax:m2",
            prompt_ref="p.j2",
            skills=("s1",),
            tools=("t1",),
            memory=MemoryScope(read=("m1",)),
            handoff=HandoffPolicy(max_handoffs=2),
            policy_ref="strict",
            max_turns=20,
            timeout_s=30.0,
            tenant_aware=False,
            feature_flag="F1",
        )
        assert spec.prompt_ref == "p.j2"
        assert spec.skills == ("s1",)
        assert spec.tools == ("t1",)
        assert spec.memory.read == ("m1",)
        assert spec.handoff.max_handoffs == 2
        assert spec.policy_ref == "strict"
        assert spec.max_turns == 20
        assert spec.timeout_s == 30.0
        assert spec.tenant_aware is False
        assert spec.feature_flag == "F1"

    def test_equality(self) -> None:
        s1 = AgentSpec(id="a", version="1", model="m")
        s2 = AgentSpec(id="a", version="1", model="m")
        assert s1 == s2
        s3 = AgentSpec(id="b", version="1", model="m")
        assert s1 != s3

    def test_frozen(self) -> None:
        spec = AgentSpec(id="a", version="1", model="m")
        with pytest.raises(Exception):  # dataclasses.FrozenInstanceError
            spec.id = "b"  # type: ignore[misc]
