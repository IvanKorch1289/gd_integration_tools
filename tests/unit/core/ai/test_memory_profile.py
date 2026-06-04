"""Unit tests for src.backend.core.ai.memory_profile."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.ai.memory_profile import MemoryKind, MemoryProfileSpec


class TestMemoryKind:
    def test_values(self) -> None:
        assert MemoryKind.WORKING == "working"
        assert MemoryKind.EPISODIC == "episodic"
        assert MemoryKind.SEMANTIC == "semantic"
        assert MemoryKind.PROCEDURAL == "procedural"


class TestMemoryProfileSpec:
    def test_minimal(self) -> None:
        spec = MemoryProfileSpec(
            id="episodic_lt",
            kind=MemoryKind.EPISODIC,
            store="memory_postgres",
            namespace_template="tenant:${tenant_id}:episodic",
        )
        assert spec.id == "episodic_lt"
        assert spec.kind == MemoryKind.EPISODIC
        assert spec.retention_days is None
        assert spec.access == "scoped"
        assert spec.consolidation == "none"
        assert spec.schema_ref is None

    def test_full(self) -> None:
        spec = MemoryProfileSpec(
            id="working_short",
            kind=MemoryKind.WORKING,
            store="memory_redis",
            namespace_template="sess:${session_id}",
            retention_days=7,
            access="shared-read",
            consolidation="summarize",
            schema_ref="schemas/working.json",
        )
        assert spec.retention_days == 7
        assert spec.access == "shared-read"
        assert spec.consolidation == "summarize"
        assert spec.schema_ref == "schemas/working.json"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            MemoryProfileSpec(
                id="", kind=MemoryKind.WORKING, store="x", namespace_template="t"
            )

    def test_empty_store_raises(self) -> None:
        with pytest.raises(ValidationError):
            MemoryProfileSpec(
                id="x", kind=MemoryKind.WORKING, store="", namespace_template="t"
            )

    def test_invalid_retention_raises(self) -> None:
        with pytest.raises(ValidationError):
            MemoryProfileSpec(
                id="x",
                kind=MemoryKind.WORKING,
                store="x",
                namespace_template="t",
                retention_days=0,
            )

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            MemoryProfileSpec(
                id="x",
                kind=MemoryKind.WORKING,
                store="x",
                namespace_template="t",
                unknown_field=123,
            )
