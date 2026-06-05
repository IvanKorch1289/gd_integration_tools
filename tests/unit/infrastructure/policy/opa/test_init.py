"""Unit tests for src.backend.infrastructure.policy.opa public API."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.policy.opa import OPAClient, PolicyDecision
from src.backend.infrastructure.policy.opa import __all__ as opa_all


@pytest.mark.unit
class TestOPAInit:
    def test_all_exports(self) -> None:
        assert set(opa_all) == {"OPAClient", "PolicyDecision"}

    def test_opa_client_is_class(self) -> None:
        assert isinstance(OPAClient, type)

    def test_policy_decision_is_class(self) -> None:
        assert isinstance(PolicyDecision, type)
