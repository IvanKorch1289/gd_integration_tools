"""P0-S4 (audit 2026-08-18): capability gate fail-closed semantics.

Без fix — ``_capability_gate is None`` → silent allow (любая prompt injection
проходит без проверки). С fix — в production (ai_policy_enforce=True)
raise ``CapabilityDeniedError``; в dev (FF off) — log + allow.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.core.ai.gateway_models import AIRequest
from src.backend.core.ai.gateway_pipeline_mixin.policy_mixin import PolicyMixin


class _StubGateway(PolicyMixin):
    """Минимальный stub для тестирования PolicyMixin в изоляции."""

    def __init__(self, *, capability_gate, ai_policy_enforce: bool = True) -> None:
        self._capability_gate = capability_gate
        self._policy_enforce = ai_policy_enforce

    @property
    def _ai_policy_enforce(self) -> bool:
        return self._policy_enforce


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_capability_gate_fail_closed_in_production() -> None:
    """ai_policy_enforce=True + capability_gate=None → raise."""
    from src.backend.core.security.capabilities.errors import CapabilityDeniedError

    request = AIRequest(
        workflow_id="credit_check", tenant_id="t1", correlation_id="c-001",
    )
    gw = _StubGateway(capability_gate=None, ai_policy_enforce=True)

    with patch(
        "src.backend.core.config.features.feature_flags.ai_policy_enforce",
        True,
        create=True,
    ):
        with pytest.raises(CapabilityDeniedError) as exc_info:
            await gw._check_capability(request)
        assert "capability_gate_not_configured" in str(exc_info.value).lower() or \
               "capability" in str(exc_info.value).lower()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_no_capability_gate_allows_in_dev() -> None:
    """ai_policy_enforce=False + capability_gate=None → silent allow (dev mode)."""
    request = AIRequest(
        workflow_id="credit_check", tenant_id="t1", correlation_id="c-001",
    )
    gw = _StubGateway(capability_gate=None, ai_policy_enforce=False)

    with patch(
        "src.backend.core.config.features.feature_flags.ai_policy_enforce",
        False,
        create=True,
    ):
        # Не должно raise
        await gw._check_capability(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capability_gate_without_check_attr_fail_closed_in_production() -> None:
    """gate.check отсутствует → treated как missing → fail-closed в production."""
    from src.backend.core.security.capabilities.errors import CapabilityDeniedError

    request = AIRequest(
        workflow_id="credit_check", tenant_id="t1", correlation_id="c-001",
    )
    gate = object()  # нет атрибута .check
    gw = _StubGateway(capability_gate=gate, ai_policy_enforce=True)

    with patch(
        "src.backend.core.config.features.feature_flags.ai_policy_enforce",
        True,
        create=True,
    ):
        with pytest.raises(CapabilityDeniedError):
            await gw._check_capability(request)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_capability_gate_check_none_fail_closed_in_production() -> None:
    """gate.check = None → treated as missing → fail-closed в production."""
    from src.backend.core.security.capabilities.errors import CapabilityDeniedError

    request = AIRequest(
        workflow_id="credit_check", tenant_id="t1", correlation_id="c-001",
    )
    gate = type("G", (), {"check": None})()
    gw = _StubGateway(capability_gate=gate, ai_policy_enforce=True)

    with patch(
        "src.backend.core.config.features.feature_flags.ai_policy_enforce",
        True,
        create=True,
    ):
        with pytest.raises(CapabilityDeniedError):
            await gw._check_capability(request)
