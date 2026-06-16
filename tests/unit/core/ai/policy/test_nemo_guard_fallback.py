"""Regression test для S93 W1 C7: NeMo guard fix.

Покрывает:
- Logger определён (regression: был NameError до фикса)
- NeMo guard без fallback → warning + return None
- NeMo guard с fallback → delegate to llm_guard (mocked)
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.core.ai.errors import GuardResult
from src.backend.core.ai.policy.enforcer import AIPolicyEnforcer
from src.backend.core.ai.policy.enforcer.input_guard_mixin import (
    _NEMO_TO_LLM_GUARD_FALLBACK,
    InputGuardMixin,
)
from src.backend.core.ai.policy.spec import GuardRef


def test_logger_is_defined_at_module_level() -> None:
    """Regression: NameError если logger не определён."""
    from src.backend.core.ai.policy.enforcer import input_guard_mixin

    assert hasattr(input_guard_mixin, "logger")
    assert input_guard_mixin.logger is not None


def test_nemo_fallback_map_is_populated() -> None:
    """Mapping NeMo → llm_guard scanner names существует."""
    assert "nemo:colang:topics" in _NEMO_TO_LLM_GUARD_FALLBACK
    assert "nemo:moderation" in _NEMO_TO_LLM_GUARD_FALLBACK
    assert all(v.startswith("llm_guard:") for v in _NEMO_TO_LLM_GUARD_FALLBACK.values())


@pytest.mark.asyncio
async def test_nemo_guard_without_fallback_returns_none(caplog) -> None:
    """NeMo guard без mapping → warning + None (graceful degradation)."""
    enforcer = AIPolicyEnforcer()
    ref = GuardRef(name="nemo:unknown_pattern", on_block="warn")

    with caplog.at_level("WARNING"):
        result = await enforcer._guard_input_one("test prompt", ref)

    assert result is None
    assert "nemo guard" in caplog.text.lower()
    assert "no fallback" in caplog.text.lower()


@pytest.mark.asyncio
async def test_nemo_guard_with_fallback_delegates_to_llm_guard() -> None:
    """NeMo guard с mapping → delegate to _guard_input_llm_guard."""
    enforcer = AIPolicyEnforcer()
    ref = GuardRef(name="nemo:colang:topics", on_block="warn")

    expected_result = GuardResult(
        verdict="passed", guard_name="llm_guard:BanTopics", categories=[]
    )

    with patch.object(
        InputGuardMixin,
        "_guard_input_llm_guard",
        new=AsyncMock(return_value=expected_result),
    ) as mock:
        result = await enforcer._guard_input_one("test prompt", ref)

    assert result is expected_result
    mock.assert_awaited_once()
    # Verify mapped ref был создан
    call_args = mock.await_args
    mapped_ref = call_args[0][1]  # second positional arg = mapped_ref
    assert mapped_ref.name == "llm_guard:BanTopics"
    assert mapped_ref.on_block == "warn"
