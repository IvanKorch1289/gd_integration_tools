"""S85 W3: regression test для ai_gateway_enforce default = True.

V2 P0 #1 reports default=False, но S25 W1 уже выставил default=True.
W3 — CI guard: если default изменится на False → test fail.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.unit


def test_ai_gateway_enforce_default_is_true() -> None:
    """V2 P0 #1 regression guard: ai_gateway_enforce default = True.

    S25 W1 установил default=True (ADR-NEW-19). Если кто-то изменит
    на False — silent pass-through вернётся → bypass paths работают.
    """
    from src.backend.core.config.features.sprints_24_27 import Sprints2427Flags

    config = Sprints2427Flags()
    assert config.ai_gateway_enforce is True, (
        "ai_gateway_enforce default changed to False! "
        "S85 W1 _legacy_invoke was removed, AIGatewayEnforcementRequiredError "
        "will now block all production traffic. Restore default=True."
    )
