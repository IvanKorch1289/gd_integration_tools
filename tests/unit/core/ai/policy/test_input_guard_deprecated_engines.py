"""Coverage tests для input_guard_deprecated_engines (Sprint 5 continuation).

TDD: edge cases для input_guard_mixin.py при работе с deprecated engines.

S172 audit:
- llm_guard upstream archived 2026-07-16
- rebuff upstream archived 2026-07-16
- lakera — только canonical engine

Coverage targets:
- llm_guard:* → GuardrailViolationError (not silent pass)
- rebuff:* → GuardrailViolationError
- Unknown engine → None (skip with warning)
- fail vs warn vs dlq modes
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.core.ai.errors import GuardrailViolationError
from src.backend.core.ai.policy.enforcer.input_guard_mixin import InputGuardMixin
from src.backend.core.ai.policy.spec import GuardRef


class _StubEnforcer(InputGuardMixin):
    """Minimal subclass to test mixin methods in isolation."""

    def __init__(self) -> None:
        self._handle_guard_block = AsyncMock()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_guard_engine_fails_closed() -> None:
    """llm_guard:* (deprecated, archived 2026-07-16) → fail-closed."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="llm_guard:safe_v3", on_block="fail")

    with pytest.raises(GuardrailViolationError, match="llm_guard_archived"):
        await enforcer._guard_input_one(
            prompt="test prompt",
            ref=ref,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_llm_guard_engine_warn_mode_passes() -> None:
    """llm_guard:* + on_block=warn → warn+continue (not raise)."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="llm_guard:safe_v3", on_block="warn")

    result = await enforcer._guard_input_one(
        prompt="test prompt",
        ref=ref,
    )
    assert result is not None
    assert result.verdict == "warned"
    assert "llm_guard_archived" in result.categories


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuff_engine_fails_closed() -> None:
    """rebuff:* (deprecated, archived 2026-07-16) → fail-closed."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="rebuff:pi", on_block="fail")

    with pytest.raises(GuardrailViolationError, match="rebuff_archived"):
        await enforcer._guard_input_one(
            prompt="test prompt",
            ref=ref,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_rebuff_engine_warn_mode_passes() -> None:
    """rebuff:* + on_block=warn → warn+continue."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="rebuff:pi", on_block="warn")

    result = await enforcer._guard_input_one(
        prompt="test prompt",
        ref=ref,
    )
    assert result is not None
    assert result.verdict == "warned"
    assert "rebuff_archived" in result.categories


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_engine_returns_none_skip_when_warn() -> None:
    """Unknown engine + on_block=warn → None (skip with warning, no raise).

    Backward compat для custom engines или unsupported names — только в warn-режиме.
    """
    enforcer = _StubEnforcer()
    ref = GuardRef(name="custom:engine", on_block="warn")

    result = await enforcer._guard_input_one(
        prompt="test prompt",
        ref=ref,
    )
    # Unknown engine + warn → пропускается (None result)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_unknown_engine_fails_closed_when_fail() -> None:
    """P0-S3 (audit 2026-08-18): Unknown engine + on_block=fail → fail-closed.

    Без fix неизвестный guard silently пропускался, и политика молча нарушалась.
    """
    enforcer = _StubEnforcer()
    ref = GuardRef(name="custom:engine", on_block="fail")

    with pytest.raises(GuardrailViolationError, match="unknown_guard"):
        await enforcer._guard_input_one(
            prompt="test prompt",
            ref=ref,
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nemo_engine_deferred_returns_none_when_warn() -> None:
    """nemo:* — deferred integration (S172). on_block=warn → None без raise."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="nemo:colang:topics", on_block="warn")

    result = await enforcer._guard_input_one(
        prompt="test prompt",
        ref=ref,
    )
    # nemo deferred + warn → None (per S172 audit F4.1)
    assert result is None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_nemo_engine_fails_closed_when_fail() -> None:
    """P0-S3 (audit 2026-08-18): nemo + on_block=fail → fail-closed.

    Без fix credit_check_strict.policy.yaml декларирует ``nemo:colang:topics``
    с ``on_block: fail``, но guard silently skip → политика молча нарушалась.
    """
    enforcer = _StubEnforcer()
    ref = GuardRef(name="nemo:colang:topics", on_block="fail")

    with pytest.raises(GuardrailViolationError, match="guard_provider_unavailable"):
        await enforcer._guard_input_one(
            prompt="test prompt",
            ref=ref,
        )
