"""Unit tests for src.backend.core.ai.skill_pack."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.ai.skill_pack import SkillPackSpec


class TestSkillPackSpec:
    def test_minimal(self) -> None:
        spec = SkillPackSpec(id="pack1", skills=["s1"])
        assert spec.id == "pack1"
        assert spec.description == ""
        assert spec.skills == ["s1"]
        assert spec.retrieval_policy == "none"
        assert spec.post_processing == "none"
        assert spec.input_schema is None
        assert spec.output_schema is None

    def test_full(self) -> None:
        spec = SkillPackSpec(
            id="pack1",
            description="desc",
            skills=["s1", "s2"],
            input_schema="in.json",
            output_schema="out.json",
            retrieval_policy="semantic",
            post_processing="dedup",
        )
        assert spec.description == "desc"
        assert spec.retrieval_policy == "semantic"
        assert spec.post_processing == "dedup"

    def test_empty_id_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillPackSpec(id="", skills=["s1"])

    def test_empty_skills_raises(self) -> None:
        with pytest.raises(ValidationError):
            SkillPackSpec(id="pack1", skills=[])

    def test_extra_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            SkillPackSpec(id="pack1", skills=["s1"], unknown=123)
