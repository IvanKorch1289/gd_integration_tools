"""Unit-тесты для :class:`GuardrailsApplyProcessor` (S27 W2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply import (
    GuardrailsApplyProcessor,
)


@dataclass
class _FakeGuardResult:
    safe: bool
    flagged_categories: list[str] = field(default_factory=list)


class _FakeRuntime:
    """Fake :class:`LlamaGuardRuntime` для unit-тестов."""

    def __init__(self, result: _FakeGuardResult) -> None:
        self.result = result
        self.calls: list[tuple[str, list[str] | None]] = []

    async def classify(
        self, text: str, categories: list[str] | None = None
    ) -> _FakeGuardResult:
        self.calls.append((text, categories))
        return self.result


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_stage() -> None:
    with pytest.raises(ValueError, match="stage must be"):
        GuardrailsApplyProcessor(stage="middle")  # type: ignore[arg-type]


def test_init_validates_on_block() -> None:
    with pytest.raises(ValueError, match="on_block must be"):
        GuardrailsApplyProcessor(on_block="ignore")  # type: ignore[arg-type]


def test_default_source_depends_on_stage() -> None:
    p_in = GuardrailsApplyProcessor(stage="input")
    p_out = GuardrailsApplyProcessor(stage="output")
    assert p_in.source_property == "body"
    assert p_out.source_property == "agent_result.content"


@pytest.mark.asyncio
async def test_safe_text_passes(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    rt = _FakeRuntime(_FakeGuardResult(safe=True))
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: rt)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="hello world"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="fail")
    await proc.process(ex, context)

    verdict = ex.get_property("guardrails_verdict")
    assert verdict == {"input": {"safe": True, "flagged_categories": [], "stage": "input"}}
    assert ex.error is None
    assert not ex.stopped


@pytest.mark.asyncio
async def test_unsafe_on_block_fail_stops(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    rt = _FakeRuntime(_FakeGuardResult(safe=False, flagged_categories=["hate"]))
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: rt)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="bad text"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="fail")
    await proc.process(ex, context)

    assert ex.error is not None
    assert "blocked by Llama Guard" in ex.error
    assert ex.stopped


@pytest.mark.asyncio
async def test_unsafe_on_block_dlq(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    rt = _FakeRuntime(_FakeGuardResult(safe=False, flagged_categories=["violence"]))
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: rt)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="bad"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="dlq")
    await proc.process(ex, context)

    dlq = ex.get_property("dlq_reason")
    assert dlq is not None
    assert dlq["flagged_categories"] == ["violence"]
    assert ex.stopped


@pytest.mark.asyncio
async def test_unsafe_on_block_warn_continues(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    rt = _FakeRuntime(_FakeGuardResult(safe=False, flagged_categories=["unsafe"]))
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: rt)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="warn-only"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="warn")
    await proc.process(ex, context)

    verdict = ex.get_property("guardrails_verdict")
    assert verdict["input"]["safe"] is False
    assert not ex.stopped
    assert ex.error is None


@pytest.mark.asyncio
async def test_runtime_unavailable_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: None)
    )

    ex: Exchange[Any] = Exchange(in_message=Message(body="hello"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="fail")
    await proc.process(ex, context)

    assert ex.error is None
    assert ex.get_property("guardrails_verdict") is None


@pytest.mark.asyncio
async def test_output_stage_reads_from_agent_result(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    rt = _FakeRuntime(_FakeGuardResult(safe=True))
    monkeypatch.setattr(
        GuardrailsApplyProcessor, "_resolve_runtime", staticmethod(lambda: rt)
    )

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "completion text"})
    proc = GuardrailsApplyProcessor(stage="output")
    await proc.process(ex, context)

    assert rt.calls[0][0] == "completion text"


@pytest.mark.asyncio
async def test_feature_flag_off_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", False)

    ex: Exchange[Any] = Exchange(in_message=Message(body="text"))
    proc = GuardrailsApplyProcessor(stage="input", on_block="fail")
    await proc.process(ex, context)

    assert ex.get_property("guardrails_verdict") is None


def test_to_spec_round_trip() -> None:
    proc = GuardrailsApplyProcessor(
        stage="output",
        source_property="agent_result.structured.reasoning",
        on_block="fail",
        categories=["hate", "violence"],
    )
    spec = proc.to_spec()
    assert spec == {
        "guardrails_apply": {
            "stage": "output",
            "on_block": "fail",
            "source_property": "agent_result.structured.reasoning",
            "categories": ["hate", "violence"],
        }
    }


def test_to_spec_default_source_omitted() -> None:
    """``source_property`` равный default не должен попадать в spec."""
    proc = GuardrailsApplyProcessor(stage="input")
    spec = proc.to_spec()
    assert "source_property" not in spec["guardrails_apply"]
