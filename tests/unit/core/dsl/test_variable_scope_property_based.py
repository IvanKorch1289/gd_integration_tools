"""S45 W4 — Stream C (additional): Hypothesis tests for VariableScope parsing.

Tests invariants of VariableScope.parse():
1. Round-trip: parse(scope_str) → str(parse(scope)) == scope_str
2. global_scope() parses correctly
3. for_tenant(id) → parse(str) roundtrips
4. for_route(id) → parse(str) roundtrips
"""

from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st


@pytest.fixture(scope="module")
def scope_class() -> Any:
    """Import VariableScope (sync, no fixture overhead per test)."""
    from src.backend.core.dsl.variables import VariableScope

    return VariableScope


@given(
    tenant_id=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    ),
)
@settings(max_examples=20, deadline=None)
def test_tenant_scope_roundtrip(scope_class: Any, tenant_id: str) -> None:
    """for_tenant(id) → str() → parse() → equals original."""
    scope = scope_class.for_tenant(tenant_id)
    scope_str = str(scope)
    parsed = scope_class.parse(scope_str)
    assert parsed.kind == "tenant"
    assert parsed.identifier == tenant_id


@given(
    route_id=st.text(
        min_size=1,
        max_size=20,
        alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd")),
    ),
)
@settings(max_examples=20, deadline=None)
def test_route_scope_roundtrip(scope_class: Any, route_id: str) -> None:
    """for_route(id) → str() → parse() → equals original."""
    scope = scope_class.for_route(route_id)
    scope_str = str(scope)
    parsed = scope_class.parse(scope_str)
    assert parsed.kind == "route"
    assert parsed.identifier == route_id


def test_global_scope_known_constants(scope_class: Any) -> None:
    """global_scope() produces a scope with empty identifier."""
    scope = scope_class.global_scope()
    assert scope.kind == "global"
    assert scope.identifier == ""
    # Roundtrip
    parsed = scope_class.parse(str(scope))
    assert parsed.kind == "global"
    assert parsed.identifier == ""
