"""Unit-тесты для :class:`AgentBranchProcessor` (S27 W1)."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.agent_dsl.agent_branch import (
    AgentBranchProcessor,
)
from src.backend.dsl.engine.processors.base import BaseProcessor


class _RecordingProcessor(BaseProcessor):
    """Записывает факт вызова в exchange.property для проверки в тестах."""

    def __init__(self, tag: str) -> None:
        super().__init__(name=f"rec:{tag}")
        self.tag = tag

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        del context
        executed = exchange.get_property("_branch_executed", [])
        executed = list(executed) + [self.tag]
        exchange.set_property("_branch_executed", executed)

    def to_spec(self) -> dict[str, Any]:
        return {"recording": {"tag": self.tag}}


@pytest.fixture
def context() -> ExecutionContext:
    return ExecutionContext()


def test_init_validates_source_property() -> None:
    with pytest.raises(ValueError, match="source_property обязателен"):
        AgentBranchProcessor(source_property="", branches={"a": []})


def test_init_validates_branches_or_default() -> None:
    with pytest.raises(ValueError, match="branches или default"):
        AgentBranchProcessor(source_property="x.y", branches={}, default=None)


@pytest.mark.asyncio
async def test_branch_match_dispatches_to_correct_branch(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "approve"})

    proc = AgentBranchProcessor(
        source_property="agent_result.content",
        branches={
            "approve": [_RecordingProcessor("APPROVE_BRANCH")],
            "reject": [_RecordingProcessor("REJECT_BRANCH")],
        },
        default=[_RecordingProcessor("DEFAULT")],
    )
    await proc.process(ex, context)

    assert ex.get_property("_branch_executed") == ["APPROVE_BRANCH"]
    assert ex.get_property("agent_branch_taken") == "approve"


@pytest.mark.asyncio
async def test_branch_fallback_default(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "unknown_verdict"})

    proc = AgentBranchProcessor(
        source_property="agent_result.content",
        branches={"approve": [_RecordingProcessor("APPROVE")]},
        default=[_RecordingProcessor("FALLBACK")],
    )
    await proc.process(ex, context)

    assert ex.get_property("_branch_executed") == ["FALLBACK"]
    assert ex.get_property("agent_branch_taken") == "default"


@pytest.mark.asyncio
async def test_branch_skip_when_no_match_no_default(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "no_match"})

    proc = AgentBranchProcessor(
        source_property="agent_result.content",
        branches={"approve": [_RecordingProcessor("APPROVE")]},
    )
    await proc.process(ex, context)

    assert ex.get_property("_branch_executed", []) == []
    assert ex.get_property("agent_branch_taken") == "skip"


@pytest.mark.asyncio
async def test_branch_nested_dot_path(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """Глубокий dot-path: ``agent_result.structured.verdict``."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"structured": {"verdict": "reject", "score": 0.2}})

    proc = AgentBranchProcessor(
        source_property="agent_result.structured.verdict",
        branches={
            "approve": [_RecordingProcessor("APPROVE")],
            "reject": [_RecordingProcessor("REJECT")],
        },
    )
    await proc.process(ex, context)
    assert ex.get_property("_branch_executed") == ["REJECT"]


@pytest.mark.asyncio
async def test_feature_flag_off_is_pass_through(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", False)

    ex: Exchange[Any] = Exchange()
    ex.set_property("agent_result", {"content": "approve"})
    proc = AgentBranchProcessor(
        source_property="agent_result.content",
        branches={"approve": [_RecordingProcessor("APPROVE")]},
    )
    await proc.process(ex, context)

    assert ex.get_property("_branch_executed") is None


def test_to_spec_round_trip() -> None:
    proc = AgentBranchProcessor(
        source_property="agent_result.content",
        branches={"approve": [_RecordingProcessor("APPROVE")]},
        default=[_RecordingProcessor("DEFAULT")],
    )
    spec = proc.to_spec()
    assert spec == {
        "agent_branch": {
            "source_property": "agent_result.content",
            "branches": {"approve": [{"recording": {"tag": "APPROVE"}}]},
            "default": [{"recording": {"tag": "DEFAULT"}}],
        }
    }
