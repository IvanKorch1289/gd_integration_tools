"""Smoke-тесты расширенного :class:`AgentInvokeDeclaration` (S28 W2).

Проверяют:
* Memory orchestration fields (memory_scope, write_episode, namespace_template,
  inject_memory, recall_on);
* WorkflowBuilder.invoke_agent() с новыми параметрами;
* Новые step types: ReflectDeclaration, CheckpointDeclaration,
  GuardrailDeclaration, EscalateDeclaration;
* WorkflowBuilder.reflect(), checkpoint(), guardrail(), escalate().
"""

from __future__ import annotations

import pytest

from src.backend.dsl.workflow.builder import WorkflowBuilder
from src.backend.dsl.workflow.spec import (
    AgentInvokeDeclaration,
    CheckpointDeclaration,
    EscalateDeclaration,
    GuardrailDeclaration,
    MemoryScope,
    ReflectDeclaration,
    WorkflowDeclaration,
)


def test_agent_invoke_declaration_minimal() -> None:
    """AgentInvokeDeclaration с минимальными required полями."""
    decl = AgentInvokeDeclaration(agent_id="credit_advisor")
    assert decl.agent_id == "credit_advisor"
    assert decl.durable is False
    assert decl.memory_scope is None
    assert decl.write_episode is False
    assert decl.inject_memory is False


def test_agent_invoke_declaration_full_memory_fields() -> None:
    """AgentInvokeDeclaration с полным набором memory orchestration полей."""
    memory_scope = MemoryScope(
        read=("episodic", "semantic"),
        write=("episodic",),
        mode="scoped",
        write_strategy="background",
    )
    decl = AgentInvokeDeclaration(
        agent_id="credit_advisor",
        durable=True,
        input_context="${body.query}",
        memory_scope=memory_scope,
        write_episode=True,
        namespace_template="tenant:${tenant_id}:wf:${workflow_name}",
        inject_memory=True,
        recall_on="body.query",
        max_turns=15,
        timeout_s=90.0,
        output_key="advisor_result",
    )
    assert decl.agent_id == "credit_advisor"
    assert decl.durable is True
    assert decl.input_context == "${body.query}"
    assert decl.memory_scope is not None
    assert decl.memory_scope.read == ("episodic", "semantic")
    assert decl.write_episode is True
    assert decl.namespace_template == "tenant:${tenant_id}:wf:${workflow_name}"
    assert decl.inject_memory is True
    assert decl.recall_on == "body.query"
    assert decl.max_turns == 15
    assert decl.timeout_s == 90.0
    assert decl.output_key == "advisor_result"


def test_workflow_builder_invoke_agent_memory_fields() -> None:
    """WorkflowBuilder.invoke_agent() с memory orchestration параметрами."""
    memory_scope = MemoryScope(read=("episodic",), write=("episodic",))
    wf = (
        WorkflowBuilder("test.wf")
        .invoke_agent(
            agent_id="advisor",
            memory_scope=memory_scope,
            write_episode=True,
            namespace_template="tenant:${tenant_id}:wf:test",
            inject_memory=True,
            recall_on="body.query",
        )
        .build()
    )
    assert len(wf.steps) == 1
    step = wf.steps[0]
    assert isinstance(step, AgentInvokeDeclaration)
    assert step.memory_scope is not None
    assert step.write_episode is True
    assert step.inject_memory is True


def test_reflect_declaration() -> None:
    """ReflectDeclaration с минимальными и полными полями."""
    reflect = ReflectDeclaration(
        source_step="advisor_step",
        memory_writes=["episodic", "semantic"],
        consolidation_policy="reflect",
    )
    assert reflect.type == "reflect"
    assert reflect.source_step == "advisor_step"
    assert "episodic" in reflect.memory_writes
    assert reflect.consolidation_policy == "reflect"
    assert reflect.async_mode is True

    reflect_full = ReflectDeclaration(
        trigger="body.should_reflect",
        source_step="ai_step",
        memory_writes=["semantic"],
        consolidation_policy="summarize",
        async_mode=False,
        output_key="reflect_result",
    )
    assert reflect_full.trigger == "body.should_reflect"
    assert reflect_full.async_mode is False
    assert reflect_full.output_key == "reflect_result"


def test_checkpoint_declaration() -> None:
    """CheckpointDeclaration с минимальными и полными полями."""
    checkpoint = CheckpointDeclaration()
    assert checkpoint.type == "checkpoint"
    assert checkpoint.checkpoint_id is None
    assert checkpoint.include_steps == ()

    checkpoint_full = CheckpointDeclaration(
        checkpoint_id="chk_001",
        include_steps=("step_a", "step_b"),
        metadata={"stage": "pre_approval"},
        output_key="checkpoint_id",
    )
    assert checkpoint_full.checkpoint_id == "chk_001"
    assert checkpoint_full.include_steps == ("step_a", "step_b")
    assert checkpoint_full.metadata["stage"] == "pre_approval"
    assert checkpoint_full.output_key == "checkpoint_id"


def test_guardrail_declaration() -> None:
    """GuardrailDeclaration с минимальными и полными полями."""
    guardrail = GuardrailDeclaration(rule="max_cost_usd", threshold=0.50)
    assert guardrail.type == "guardrail"
    assert guardrail.rule == "max_cost_usd"
    assert guardrail.threshold == 0.50
    assert guardrail.on_exceed == "fail"

    guardrail_full = GuardrailDeclaration(
        rule="max_tokens",
        threshold=4096,
        on_exceed="escalate",
        target="body.usage.tokens",
        output_key="guardrail_result",
    )
    assert guardrail_full.on_exceed == "escalate"
    assert guardrail_full.target == "body.usage.tokens"
    assert guardrail_full.output_key == "guardrail_result"


def test_escalate_declaration() -> None:
    """EscalateDeclaration с минимальными и полями."""
    escalate = EscalateDeclaration(to_agent="senior_advisor")
    assert escalate.type == "escalate"
    assert escalate.to_agent == "senior_advisor"
    assert escalate.to_model is None

    escalate_full = EscalateDeclaration(
        to_agent="senior_advisor",
        to_model="minimax:m2.5",
        reason="complex_case",
        output_key="escalation_result",
    )
    assert escalate_full.to_model == "minimax:m2.5"
    assert escalate_full.reason == "complex_case"
    assert escalate_full.output_key == "escalation_result"


def test_workflow_builder_reflect() -> None:
    """WorkflowBuilder.reflect() добавляет ReflectDeclaration."""
    wf = (
        WorkflowBuilder("test.wf")
        .activity("fetch_data")
        .reflect(source_step="fetch_data", memory_writes=["semantic"])
        .build()
    )
    assert len(wf.steps) == 2
    assert isinstance(wf.steps[1], ReflectDeclaration)
    assert wf.steps[1].source_step == "fetch_data"
    assert "semantic" in wf.steps[1].memory_writes


def test_workflow_builder_checkpoint() -> None:
    """WorkflowBuilder.checkpoint() добавляет CheckpointDeclaration."""
    wf = (
        WorkflowBuilder("test.wf")
        .activity("step_a")
        .checkpoint(checkpoint_id="chk_001", include_steps=("step_a",))
        .build()
    )
    assert len(wf.steps) == 2
    assert isinstance(wf.steps[1], CheckpointDeclaration)
    assert wf.steps[1].checkpoint_id == "chk_001"


def test_workflow_builder_guardrail() -> None:
    """WorkflowBuilder.guardrail() добавляет GuardrailDeclaration."""
    wf = (
        WorkflowBuilder("test.wf")
        .invoke_agent("advisor")
        .guardrail(rule="max_cost_usd", threshold=0.50)
        .build()
    )
    assert len(wf.steps) == 2
    assert isinstance(wf.steps[1], GuardrailDeclaration)
    assert wf.steps[1].rule == "max_cost_usd"


def test_workflow_builder_escalate() -> None:
    """WorkflowBuilder.escalate() добавляет EscalateDeclaration."""
    wf = (
        WorkflowBuilder("test.wf")
        .guardrail(rule="max_cost_usd", threshold=0.50, on_exceed="escalate")
        .escalate(to_agent="senior_advisor", reason="cost_exceeded")
        .build()
    )
    assert len(wf.steps) == 2
    assert isinstance(wf.steps[1], EscalateDeclaration)
    assert wf.steps[1].to_agent == "senior_advisor"


def test_workflow_step_discriminated_union() -> None:
    """WorkflowStep correctly discriminates all 9 step types."""
    wf = (
        WorkflowBuilder("test.wf")
        .activity("act")
        .wait_for_signal("sig")
        .sleep(1.0)
        .sensor("pred")
        .invoke_agent("advisor")
        .reflect(source_step="advisor")
        .checkpoint()
        .guardrail("max_cost_usd", 0.5)
        .escalate(to_agent="fallback")
        .build()
    )
    assert len(wf.steps) == 9
    # Verify all types are present
    from src.backend.dsl.workflow.spec import (
        ActivityDeclaration,
        AgentInvokeDeclaration,
        CheckpointDeclaration,
        EscalateDeclaration,
        GuardrailDeclaration,
        ReflectDeclaration,
        SensorDeclaration,
        SignalWaitDeclaration,
        SleepDeclaration,
    )

    step_types = [type(s) for s in wf.steps]
    assert ActivityDeclaration in step_types
    assert SignalWaitDeclaration in step_types
    assert SleepDeclaration in step_types
    assert SensorDeclaration in step_types
    assert AgentInvokeDeclaration in step_types
    assert ReflectDeclaration in step_types
    assert CheckpointDeclaration in step_types
    assert GuardrailDeclaration in step_types
    assert EscalateDeclaration in step_types
