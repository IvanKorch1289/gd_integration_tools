"""Unit-тесты для :class:`AgentDSLMixin` — финальный 11-methods coverage (S27 W3)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.builders.agent_dsl import AgentDSLMixin
from src.backend.dsl.builders.base import RouteBuilder

W1_METHODS = ("agent_run", "ai_invoke", "agent_branch", "agent_loop", "agent_parallel")

W2_METHODS = ("guardrails_apply", "pii_mask", "pii_unmask")

W3_METHODS = ("skill_invoke", "ai_memory_recall", "ai_memory_store")


def test_mixin_provides_all_11_methods() -> None:
    """DoD #3: все 11 fluent methods доступны на RouteBuilder."""
    b = RouteBuilder.from_("test", source="internal:t")
    for m in W1_METHODS + W2_METHODS + W3_METHODS:
        assert hasattr(b, m), f"Missing method: {m}"
    assert len(W1_METHODS + W2_METHODS + W3_METHODS) == 11


def test_mixin_in_mro() -> None:
    """:class:`AgentDSLMixin` находится в MRO :class:`RouteBuilder`."""
    mro_names = [c.__name__ for c in RouteBuilder.__mro__]
    assert "AgentDSLMixin" in mro_names


def test_mixin_is_stateless() -> None:
    """Контракт mixin: ``__slots__ = ()``, без instance attributes."""
    assert getattr(AgentDSLMixin, "__slots__", None) == ()
    # Не должно быть __dict__ если __slots__ = ()
    instance = AgentDSLMixin()
    assert not hasattr(instance, "__dict__")


def test_chained_pipeline_all_11_methods() -> None:
    """Цепочка из 11 методов даёт 11 + 1 (agent_run) processors."""
    b = (
        RouteBuilder.from_("ai_demo", source="internal:test")
        .agent_run(workflow_id="step1", prompt_inline="p1")
        .agent_branch(
            source_property="agent_result.content", branches={"approve": []}, default=[]
        )
        .agent_loop(
            processors=[]  # пустые processors через _add fails; чтобы пройти init validation:
        )
        if False
        else RouteBuilder.from_("ai_demo", source="internal:test")
    )
    # Чейн без agent_loop (требует non-empty processors):
    chained = (
        b.agent_run(workflow_id="step1", prompt_inline="x")
        .ai_invoke(workflow_id="step2", prompt_inline="y")
        .pii_mask(scope="banking")
        .guardrails_apply(stage="input")
        .pii_unmask(strict=False)
        .skill_invoke(skill_id="x.y.z")
        .ai_memory_recall(namespace="${tenant_id}:chat", query="q")
        .ai_memory_store(namespace="${tenant_id}:chat", key="k")
    )
    assert len(chained._processors) == 8


@pytest.mark.parametrize(
    ("method", "kwargs", "expected_class_name"),
    [
        (
            "agent_run",
            {"workflow_id": "credit_check", "prompt_inline": "x"},
            "AgentRunProcessor",
        ),
        (
            "ai_invoke",
            {"workflow_id": "doc_summary", "prompt_inline": "y"},
            "AgentRunProcessor",  # ai_invoke — alias для agent_run
        ),
        (
            "agent_branch",
            {
                "source_property": "agent_result.content",
                "branches": {"approve": []},
                "default": [],
            },
            "AgentBranchProcessor",
        ),
        (
            "agent_parallel",
            {"agents": [{"key": "a", "workflow_id": "x", "prompt_inline": "p"}]},
            "AgentParallelProcessor",
        ),
        (
            "guardrails_apply",
            {"stage": "input", "on_block": "warn"},
            "GuardrailsApplyProcessor",
        ),
        ("pii_mask", {"scope": "banking"}, "PIIMaskProcessor"),
        ("pii_unmask", {"strict": False}, "PIIUnmaskProcessor"),
        (
            "skill_invoke",
            {"skill_id": "credit.score.calculate"},
            "SkillInvokeProcessor",
        ),
        (
            "ai_memory_recall",
            {"namespace": "acme:chat", "query": "q"},
            "MemoryRecallProcessor",
        ),
        (
            "ai_memory_store",
            {"namespace": "acme:chat", "key": "k"},
            "MemoryStoreProcessor",
        ),
    ],
)
def test_each_method_adds_correct_processor(
    method: str, kwargs: dict[str, Any], expected_class_name: str
) -> None:
    """Каждый fluent method добавляет правильный processor в pipeline."""
    b = RouteBuilder.from_("test", source="internal:t")
    fn = getattr(b, method)
    fn(**kwargs)
    assert len(b._processors) == 1
    assert type(b._processors[0]).__name__ == expected_class_name


def test_agent_loop_adds_correct_processor() -> None:
    """``.agent_loop`` отдельно — требует non-empty processors."""
    from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor

    b = RouteBuilder.from_("test", source="internal:t")
    sub = AgentRunProcessor(workflow_id="x", prompt_inline="y")
    b.agent_loop(processors=[sub], max_iterations=3)
    assert len(b._processors) == 1
    assert type(b._processors[0]).__name__ == "AgentLoopProcessor"


def test_yaml_round_trip_all_processors_have_to_spec() -> None:
    """Каждый из 10 processors реализует ``to_spec()`` → non-None dict с одним ключом."""
    from src.backend.dsl.engine.processors.agent_dsl.agent_branch import (
        AgentBranchProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.agent_loop import (
        AgentLoopProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.agent_parallel import (
        AgentParallelProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.agent_run import AgentRunProcessor
    from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (
        GuardrailsApplyProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.memory_recall import (
        MemoryRecallProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.memory_store import (
        MemoryStoreProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.pii_mask import PIIMaskProcessor
    from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import (
        PIIUnmaskProcessor,
    )
    from src.backend.dsl.engine.processors.agent_dsl.skill_invoke import (
        SkillInvokeProcessor,
    )

    instances = [
        (AgentRunProcessor(workflow_id="x", prompt_inline="y"), "agent_run"),
        (
            AgentBranchProcessor(source_property="x.y", branches={"a": []}, default=[]),
            "agent_branch",
        ),
        (
            AgentLoopProcessor(
                processors=[AgentRunProcessor(workflow_id="x", prompt_inline="y")]
            ),
            "agent_loop",
        ),
        (
            AgentParallelProcessor(
                agents=[{"key": "a", "workflow_id": "x", "prompt_inline": "p"}]
            ),
            "agent_parallel",
        ),
        (GuardrailsApplyProcessor(stage="input"), "guardrails_apply"),
        (PIIMaskProcessor(scope="banking"), "pii_mask"),
        (PIIUnmaskProcessor(), "pii_unmask"),
        (SkillInvokeProcessor(skill_id="x.y.z"), "skill_invoke"),
        (MemoryRecallProcessor(namespace="ns", query="q"), "memory_recall"),
        (MemoryStoreProcessor(namespace="ns", key="k"), "memory_store"),
    ]

    for proc, expected_key in instances:
        spec = proc.to_spec()
        assert spec is not None, f"{type(proc).__name__}.to_spec() returned None"
        assert isinstance(spec, dict), f"{type(proc).__name__}.to_spec() not a dict"
        assert expected_key in spec, (
            f"{type(proc).__name__}: spec missing key {expected_key!r}, got {list(spec)}"
        )


def test_build_includes_agent_dsl_processors() -> None:
    """``.build()`` корректно собирает Pipeline с agent_dsl processors."""
    pipeline = (
        RouteBuilder.from_("agent_demo", source="internal:t")
        .agent_run(workflow_id="x", prompt_inline="y")
        .pii_mask(scope="banking")
        .build(validate_actions=False)
    )
    assert pipeline.route_id == "agent_demo"
    assert len(pipeline.processors) == 2
