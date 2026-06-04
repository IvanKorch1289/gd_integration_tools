"""Unit tests for src.backend.core.interfaces.rule_engine."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.backend.core.interfaces.rule_engine import RuleEngineRepository, RulesetDoc


class TestRulesetDoc:
    def test_defaults(self) -> None:
        doc = RulesetDoc(name="rs1", yaml_body="rules: []")
        assert doc.id is None
        assert doc.version == "1"
        assert doc.enabled is True
        assert doc.tenant_id is None
        assert doc.created_at is None
        assert doc.updated_at is None

    def test_validation_name_required(self) -> None:
        with pytest.raises(ValidationError):
            RulesetDoc(yaml_body="rules: []")

    def test_full(self) -> None:
        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        doc = RulesetDoc(
            id=1,
            name="rs1",
            version="2",
            yaml_body="rules: []",
            enabled=False,
            tenant_id="t1",
            created_at=now,
            updated_at=now,
        )
        assert doc.id == 1
        assert doc.enabled is False


class TestRuleEngineRepository:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def get(
                self,
                name: str,
                *,
                version: str | None = None,
                tenant_id: str | None = None,
            ) -> RulesetDoc | None:
                return None

            async def list_active(
                self, *, tenant_id: str | None = None
            ) -> list[RulesetDoc]:
                return []

            async def upsert(self, doc: RulesetDoc) -> RulesetDoc:
                return doc

            async def delete(
                self, name: str, version: str, *, tenant_id: str | None = None
            ) -> bool:
                return False

        assert isinstance(Fake(), RuleEngineRepository)

    def test_missing_method_fails(self) -> None:
        class Bad:
            pass

        assert not isinstance(Bad(), RuleEngineRepository)
