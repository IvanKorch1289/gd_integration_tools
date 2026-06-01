"""Smoke-тесты MemoryProfileSpec и SkillPackSpec (S29 W1-W2).

Проверяют:
* MemoryProfileSpec Pydantic validation;
* MemoryKind enum values;
* SkillPackSpec Pydantic validation.
"""

from __future__ import annotations

from src.backend.core.ai.memory_profile import MemoryKind, MemoryProfileSpec
from src.backend.core.ai.skill_pack import SkillPackSpec


def test_memory_kind_values() -> None:
    """MemoryKind enum имеет правильные значения."""
    assert MemoryKind.WORKING == "working"
    assert MemoryKind.EPISODIC == "episodic"
    assert MemoryKind.SEMANTIC == "semantic"
    assert MemoryKind.PROCEDURAL == "procedural"


def test_memory_profile_spec_minimal() -> None:
    """MemoryProfileSpec с минимальными required полями."""
    spec = MemoryProfileSpec(
        id="episodic_store",
        kind=MemoryKind.EPISODIC,
        store="memory_postgres",
        namespace_template="tenant:${tenant_id}:episodic",
    )
    assert spec.id == "episodic_store"
    assert spec.kind == MemoryKind.EPISODIC
    assert spec.store == "memory_postgres"
    assert spec.namespace_template == "tenant:${tenant_id}:episodic"
    assert spec.retention_days is None
    assert spec.access == "scoped"
    assert spec.consolidation == "none"


def test_memory_profile_spec_full() -> None:
    """MemoryProfileSpec с полным набором опций."""
    spec = MemoryProfileSpec(
        id="semantic_long_term",
        kind=MemoryKind.SEMANTIC,
        store="memory_qdrant",
        namespace_template="tenant:${tenant_id}:semantic",
        retention_days=365,
        access="shared-read",
        consolidation="dedup",
        schema_ref="schemas/semantic_fact.json",
    )
    assert spec.retention_days == 365
    assert spec.access == "shared-read"
    assert spec.consolidation == "dedup"
    assert spec.schema_ref == "schemas/semantic_fact.json"


def test_skill_pack_spec_minimal() -> None:
    """SkillPackSpec с минимальными required полями."""
    spec = SkillPackSpec(
        id="credit_skills",
        skills=["credit.score.calculate", "credit.check.rules"],
    )
    assert spec.id == "credit_skills"
    assert len(spec.skills) == 2
    assert spec.retrieval_policy == "none"
    assert spec.post_processing == "none"


def test_skill_pack_spec_full() -> None:
    """SkillPackSpec с полным набором опций."""
    spec = SkillPackSpec(
        id="credit_skills",
        description="Набор навыков для кредитной оценки",
        skills=["credit.score.calculate", "credit.check.rules"],
        input_schema="schemas/credit_input.json",
        output_schema="schemas/credit_output.json",
        retrieval_policy="semantic",
        post_processing="dedup",
    )
    assert spec.description == "Набор навыков для кредитной оценки"
    assert spec.input_schema == "schemas/credit_input.json"
    assert spec.output_schema == "schemas/credit_output.json"
    assert spec.retrieval_policy == "semantic"
    assert spec.post_processing == "dedup"