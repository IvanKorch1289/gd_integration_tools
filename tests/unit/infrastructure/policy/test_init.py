"""Unit tests for src.backend.infrastructure.policy public API."""

from __future__ import annotations

import pytest

from src.backend.infrastructure.policy import CasbinAdapter, OPAClient, PolicyDecision
from src.backend.infrastructure.policy import __all__ as policy_all


@pytest.mark.unit
class TestPolicyInit:
    def test_all_exports(self) -> None:
        assert set(policy_all) == {"CasbinAdapter", "OPAClient", "PolicyDecision"}

    def test_casbin_adapter_is_class(self) -> None:
        assert isinstance(CasbinAdapter, type)

    def test_opa_client_is_class(self) -> None:
        assert isinstance(OPAClient, type)

    def test_policy_decision_is_class(self) -> None:
        assert isinstance(PolicyDecision, type)
