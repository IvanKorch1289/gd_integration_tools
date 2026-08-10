"""Regression tests for P0 input guard fail-closed semantics (cycle 30).

Reproduces the original vulnerability: guard provider failure silently
degraded to ``"warned"`` instead of blocking input.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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
async def test_provider_failure_fail_closed_by_default() -> None:
    """Lakera unavailable → GuardrailViolationError (not silent warn)."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="lakera:strict", on_block="warn")

    with patch(
        "src.backend.services.ai.guardrails.lakera_client.LakeraClient",
    ) as mock_cls:
        mock_client = MagicMock()
        mock_client.screen = AsyncMock(side_effect=RuntimeError("network timeout"))
        mock_cls.return_value = mock_client

        with pytest.raises(GuardrailViolationError) as exc_info:
            await enforcer._guard_input_lakera("test prompt", ref, "warn")

        assert "guard_provider_unavailable" in str(exc_info.value)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_provider_failure_with_fail_open_warns() -> None:
    """fail_open=True → warned + audit event emitted."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="lakera:strict", on_block="warn", fail_open=True)

    with (
        patch(
            "src.backend.services.ai.guardrails.lakera_client.LakeraClient",
        ) as mock_cls,
        patch(
            "src.backend.core.audit.facade.emit_audit_safe",
        ) as mock_audit,
    ):
        mock_client = MagicMock()
        mock_client.screen = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_cls.return_value = mock_client

        result = await enforcer._guard_input_lakera("test prompt", ref, "warn")

        assert result is not None
        assert result.verdict == "warned"
        assert "guard_provider_unavailable" in result.categories
        mock_audit.assert_called_once()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_flagged_input_blocks_even_with_fail_open() -> None:
    """flagged=True always blocks, even when fail_open=True.

    The mixin calls ``self._handle_guard_block`` synchronously (it raises
    in-place for ``on_block="fail"``). We test that a flagged result does
    NOT reach the ``except`` branch (which is provider-failure only).
    """

    def _raise_block(**kwargs: object) -> None:
        raise GuardrailViolationError(
            guard_name="lakera",
            flagged_categories=["prompt_injection"],
            on_block="fail",
            content="bad",
        )

    enforcer = _StubEnforcer()
    enforcer._handle_guard_block = _raise_block  # type: ignore[method-assign]
    ref = GuardRef(name="lakera:strict", on_block="fail", fail_open=True)

    with patch(
        "src.backend.services.ai.guardrails.lakera_client.LakeraClient",
    ) as mock_cls:
        mock_result = MagicMock()
        mock_result.flagged = True
        mock_result.categories = [{"category": "prompt_injection"}]
        mock_client = MagicMock()
        mock_client.screen = AsyncMock(return_value=mock_result)
        mock_cls.return_value = mock_client

        with pytest.raises(GuardrailViolationError):
            await enforcer._guard_input_lakera("malicious prompt", ref, "fail")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_successful_guard_returns_passed() -> None:
    """flagged=False → verdict 'passed'."""
    enforcer = _StubEnforcer()
    ref = GuardRef(name="lakera:strict", on_block="fail")

    with patch(
        "src.backend.services.ai.guardrails.lakera_client.LakeraClient",
    ) as mock_cls:
        mock_result = MagicMock()
        mock_result.flagged = False
        mock_result.categories = []
        mock_client = MagicMock()
        mock_client.screen = AsyncMock(return_value=mock_result)
        mock_cls.return_value = mock_client

        result = await enforcer._guard_input_lakera("safe prompt", ref, "fail")

        assert result is not None
        assert result.verdict == "passed"
