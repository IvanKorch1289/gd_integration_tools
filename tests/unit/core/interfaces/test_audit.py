"""Unit tests for src.backend.core.interfaces.audit."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.audit import AuditBackend, AuditRecord


class TestAuditRecord:
    def test_is_dict(self) -> None:
        rec = AuditRecord({"event": "login", "actor": "u1"})
        assert rec["event"] == "login"
        assert isinstance(rec, dict)


class TestAuditBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AuditBackend()  # type: ignore[abstract]

    def test_subclass_must_implement(self) -> None:
        class Partial(AuditBackend):
            async def append(self, record: AuditRecord) -> None:
                pass

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(AuditBackend):
            async def append(self, record: AuditRecord) -> None:
                pass

            async def query(
                self, *, limit: int = 100, filters: dict[str, object] | None = None
            ) -> list[AuditRecord]:
                return []

        assert Full() is not None
