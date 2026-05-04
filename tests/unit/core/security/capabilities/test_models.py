# ruff: noqa: S101
"""Тесты CapabilityRef + DEFAULT_CAPABILITY_CATALOG (ADR-044)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.core.security.capabilities import (
    CAPABILITY_NAME_PATTERN,
    DEFAULT_CAPABILITY_CATALOG,
    CapabilityRef,
)


class TestCapabilityRef:
    def test_resource_verb_split(self) -> None:
        ref = CapabilityRef(name="db.read", scope="x")
        assert ref.resource == "db"
        assert ref.verb == "read"

    def test_frozen(self) -> None:
        ref = CapabilityRef(name="db.read", scope="x")
        with pytest.raises(ValidationError):
            ref.scope = "y"  # type: ignore[misc]

    @pytest.mark.parametrize("bad", ["db", "db.READ", "1db.read", "db..read"])
    def test_grammar_rejection(self, bad: str) -> None:
        with pytest.raises(ValidationError):
            CapabilityRef(name=bad)

    def test_pattern_constant(self) -> None:
        # Регулярка должна совпадать со всем v0-каталогом.
        import re

        compiled = re.compile(CAPABILITY_NAME_PATTERN)
        for name in DEFAULT_CAPABILITY_CATALOG:
            assert compiled.match(name), name

    def test_default_catalog_uniqueness(self) -> None:
        assert len(DEFAULT_CAPABILITY_CATALOG) == len(set(DEFAULT_CAPABILITY_CATALOG))
