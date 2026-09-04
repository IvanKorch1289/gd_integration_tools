"""Tests for core/security/capabilities/vocabulary/models.py (S99 — coverage push).

CapabilityDef dataclass + ScopeMatcher field.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import ExactAliasMatcher
from src.backend.core.security.capabilities.vocabulary.models import CapabilityDef


def test_capability_def_minimal() -> None:
    """CapabilityDef: minimal constructor (only required field 'name')."""
    matcher = ExactAliasMatcher()
    cd = CapabilityDef(name="net.outbound", matcher=matcher)
    assert cd.name == "net.outbound"
    assert cd.matcher is matcher
    assert cd.scope_required is True  # default
    assert cd.description == ""
    assert cd.public is False
    assert cd.aliases == ()


def test_capability_def_full() -> None:
    """CapabilityDef: all fields set."""
    matcher = ExactAliasMatcher()
    cd = CapabilityDef(
        name="db.read",
        matcher=matcher,
        scope_required=False,
        description="Read access to database",
        public=True,
        aliases=("db.query", "db.select"),
    )
    assert cd.name == "db.read"
    assert cd.matcher is matcher
    assert cd.scope_required is False
    assert cd.description == "Read access to database"
    assert cd.public is True
    assert cd.aliases == ("db.query", "db.select")


def test_capability_def_equality() -> None:
    """CapabilityDef: dataclass equality."""
    matcher = ExactAliasMatcher()
    cd1 = CapabilityDef(name="net.outbound", matcher=matcher)
    cd2 = CapabilityDef(name="net.outbound", matcher=matcher)
    assert cd1 == cd2


def test_capability_def_inequality_different_name() -> None:
    """CapabilityDef: разные name → not equal."""
    matcher = ExactAliasMatcher()
    cd1 = CapabilityDef(name="net.outbound", matcher=matcher)
    cd2 = CapabilityDef(name="db.read", matcher=matcher)
    assert cd1 != cd2
