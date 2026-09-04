"""Tests for core/security/authorization_gateway/policies/*PolicyDecider (S99).

Covers: casbin_policy_decider, opa_policy_decider (B-12 fix cycle 37).
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch


def test_casbin_policy_decider_alias() -> None:
    """CasbinPolicyDecider = build_casbin_policy_decider (DI alias)."""
    from src.backend.core.security.authorization_gateway.policies.casbin_policy_decider import (
        CasbinPolicyDecider,
        build_casbin_policy_decider,
    )

    assert CasbinPolicyDecider is build_casbin_policy_decider


def test_build_casbin_calls_auth_gateway() -> None:
    """build_casbin_policy_decider → AuthorizationGateway.casbin_step."""
    from src.backend.core.security.authorization_gateway.policies.casbin_policy_decider import (
        build_casbin_policy_decider,
    )

    casbin = MagicMock()
    expected_decider = MagicMock()
    with patch.object(
        __import__(
            "src.backend.core.security.authorization_gateway",
            fromlist=["AuthorizationGateway"],
        ).AuthorizationGateway,
        "casbin_step",
        return_value=expected_decider,
    ) as mock_step:
        result = build_casbin_policy_decider(casbin)
    assert result is expected_decider
    mock_step.assert_called_once_with(casbin)


def test_casbin_dunder_all() -> None:
    """__all__ = ('CasbinPolicyDecider', 'build_casbin_policy_decider')."""
    from src.backend.core.security.authorization_gateway.policies import casbin_policy_decider

    assert casbin_policy_decider.__all__ == (
        "CasbinPolicyDecider",
        "build_casbin_policy_decider",
    )


def test_opa_policy_decider_alias() -> None:
    """OPAPolicyDecider = build_opa_policy_decider (DI alias)."""
    from src.backend.core.security.authorization_gateway.policies.opa_policy_decider import (
        OPAPolicyDecider,
        build_opa_policy_decider,
    )

    assert OPAPolicyDecider is build_opa_policy_decider


def test_build_opa_calls_auth_gateway_with_policy_name() -> None:
    """build_opa_policy_decider → AuthorizationGateway.opa_step(client, policy_name)."""
    from src.backend.core.security.authorization_gateway.policies.opa_policy_decider import (
        build_opa_policy_decider,
    )

    opa = MagicMock()
    expected_decider = MagicMock()
    with patch.object(
        __import__(
            "src.backend.core.security.authorization_gateway",
            fromlist=["AuthorizationGateway"],
        ).AuthorizationGateway,
        "opa_step",
        return_value=expected_decider,
    ) as mock_step:
        result = build_opa_policy_decider(opa, policy_name="my/policy")
    assert result is expected_decider
    mock_step.assert_called_once_with(opa, "my/policy")


def test_build_opa_default_policy_name() -> None:
    """build_opa_policy_decider default policy_name='authz/default'."""
    from src.backend.core.security.authorization_gateway.policies.opa_policy_decider import (
        build_opa_policy_decider,
    )

    opa = MagicMock()
    with patch.object(
        __import__(
            "src.backend.core.security.authorization_gateway",
            fromlist=["AuthorizationGateway"],
        ).AuthorizationGateway,
        "opa_step",
        return_value=MagicMock(),
    ) as mock_step:
        build_opa_policy_decider(opa)
    mock_step.assert_called_once_with(opa, "authz/default")


def test_opa_dunder_all() -> None:
    """__all__ = ('OPAPolicyDecider', 'build_opa_policy_decider')."""
    from src.backend.core.security.authorization_gateway.policies import opa_policy_decider

    assert opa_policy_decider.__all__ == (
        "OPAPolicyDecider",
        "build_opa_policy_decider",
    )
