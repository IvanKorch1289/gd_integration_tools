"""Unit-тесты для :class:`SkillInvokeProcessor` (S27 W3)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.skill_invoke import (
    SkillInvokeProcessor,
)


class _FakeSkillRegistry:
    def __init__(self, result: Any = None, raises: Exception | None = None) -> None:
        self.result = result
        self.raises = raises
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def invoke(self, skill_id: str, **kwargs: Any) -> Any:
        self.calls.append((skill_id, kwargs))
        if self.raises is not None:
            raise self.raises
        return self.result


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_skill_id() -> None:
    with pytest.raises(ValueError, match="skill_id обязателен"):
        SkillInvokeProcessor(skill_id="")


def test_capability_scope_returns_skill_id() -> None:
    proc = SkillInvokeProcessor(skill_id="credit.score.calculate")
    ex: Exchange[Any] = Exchange()
    assert proc._capability_scope(ex) == "credit.score.calculate"


@pytest.mark.asyncio
async def test_happy_path_writes_skill_result(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    registry = _FakeSkillRegistry(result={"score": 750})
    monkeypatch.setattr(
        SkillInvokeProcessor, "_resolve_registry", staticmethod(lambda: registry)
    )

    ex: Exchange[Any] = Exchange(
        in_message=Message(body={"customer_id": 42, "income": 100000})
    )
    proc = SkillInvokeProcessor(skill_id="credit.score.calculate")
    await proc.process(ex, context)

    assert ex.get_property("skill_result") == {"score": 750}
    assert len(registry.calls) == 1
    assert registry.calls[0][0] == "credit.score.calculate"
    assert registry.calls[0][1] == {"customer_id": 42, "income": 100000}


@pytest.mark.asyncio
async def test_scaffold_not_implemented_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """SkillRegistry.invoke в scaffold-режиме raises NotImplementedError."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    registry = _FakeSkillRegistry(raises=NotImplementedError("S26 W5"))
    monkeypatch.setattr(
        SkillInvokeProcessor, "_resolve_registry", staticmethod(lambda: registry)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={}))
    proc = SkillInvokeProcessor(skill_id="x.y.z")
    await proc.process(ex, context)

    assert ex.get_property("skill_result") is None
    assert ex.error is None


@pytest.mark.asyncio
async def test_unknown_skill_id_fails(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    registry = _FakeSkillRegistry(raises=KeyError("not found"))
    monkeypatch.setattr(
        SkillInvokeProcessor, "_resolve_registry", staticmethod(lambda: registry)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={}))
    proc = SkillInvokeProcessor(skill_id="missing.skill")
    await proc.process(ex, context)

    assert ex.error is not None
    assert "не зарегистрирован" in ex.error
    assert ex.stopped


@pytest.mark.asyncio
async def test_registry_unavailable_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        SkillInvokeProcessor, "_resolve_registry", staticmethod(lambda: None)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body={}))
    proc = SkillInvokeProcessor(skill_id="x.y.z")
    await proc.process(ex, context)

    assert ex.error is None


@pytest.mark.asyncio
async def test_params_extraction_from_dot_path(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    registry = _FakeSkillRegistry(result="ok")
    monkeypatch.setattr(
        SkillInvokeProcessor, "_resolve_registry", staticmethod(lambda: registry)
    )

    ex: Exchange[Any] = Exchange(
        in_message=Message(body={"params": {"key": "val"}, "other": "x"})
    )
    proc = SkillInvokeProcessor(skill_id="x.y.z", params_property="body.params")
    await proc.process(ex, context)

    assert registry.calls[0][1] == {"key": "val"}


def test_to_spec_round_trip() -> None:
    proc = SkillInvokeProcessor(
        skill_id="credit.score.calculate",
        params_property="property:my_params",
        result_property="custom_skill_result",
    )
    spec = proc.to_spec()
    assert spec == {
        "skill_invoke": {
            "skill_id": "credit.score.calculate",
            "params_property": "property:my_params",
            "result_property": "custom_skill_result",
        }
    }
