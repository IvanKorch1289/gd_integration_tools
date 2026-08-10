"""Tests for ProceduralMemory (cycle 65).

Stream E.7 — procedural memory: "как делать" — named sequence
of steps (playbook / SOP / runbook) stored в Postgres.

Cycle 65 invariant: tests catch regressions in procedural storage
that could lead to silent SOP corruption в banking AI agents.
"""


from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_mock_session_factory(rows: list[Any]) -> Any:
    """Создаёт async session_factory with fake session supporting add/commit/refresh/execute."""

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            class _FakeScalars:
                def __init__(self, rs):
                    self._rows = rs

                def all(self):
                    return self._rows
            return _FakeScalars(self._rows)

    class FakeSession:
        def __init__(self, rows, store):
            self._rows = rows
            self._store = store
            self.added: list = []
            self.committed = False

        def add(self, row):
            self.added.append(row)
            self._rows.append(row)
            if getattr(row, "id", None) is None:
                row.id = len(self._rows)

        async def commit(self):
            self.committed = True

        async def refresh(self, row):
            pass

        async def execute(self, stmt):
            # Order by updated_at desc (default for Procedural).
            sorted_rows = sorted(
                self._rows, key=lambda r: getattr(r, "updated_at", None), reverse=True
            )
            limit_val = getattr(stmt, "_limit", None)
            if limit_val is not None:
                sorted_rows = sorted_rows[:limit_val]
            return FakeResult(sorted_rows)

    _args: list = []

    @asynccontextmanager
    async def factory():
        session = FakeSession(rows, rows)
        _args.append(session)
        yield session

    factory._args = _args  # type: ignore[attr-defined]
    return factory


class TestProceduralMemoryInit:
    """__init__ stores session_factory."""

    def test_init_stores_session_factory(self) -> None:
        """__init__ stores session_factory parameter."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = MagicMock()
        mem = ProceduralMemory(session_factory=factory)
        assert mem._session_factory is factory


class TestProceduralMemoryAdd:
    """add() method: insert procedural record → return id."""

    @pytest.mark.asyncio
    async def test_add_returns_integer_id(self) -> None:
        """add() возвращает integer id из row.id."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.add(name="kredit_check_v1")

        assert result == 1, f"Expected 1, got {result}"

    @pytest.mark.asyncio
    async def test_add_sets_required_fields(self) -> None:
        """add() устанавливает name в LangMemProcedural."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        await mem.add(name="kredit_check_v1")

        session = factory._args[0]
        assert len(session.added) == 1
        row = session.added[0]
        assert row.name == "kredit_check_v1"

    @pytest.mark.asyncio
    async def test_add_with_description_steps_tenant(self) -> None:
        """add() сохраняет description, steps, tenant fields."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        steps = {"step1": "verify", "step2": "approve"}
        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        await mem.add(
            name="sop_v1",
            description="Кредитный скоринг SOP",
            steps=steps,
            tenant="acme",
        )

        session = factory._args[0]
        row = session.added[0]
        assert row.name == "sop_v1"
        assert row.description == "Кредитный скоринг SOP"
        assert row.steps == steps
        assert row.tenant == "acme"

    @pytest.mark.asyncio
    async def test_add_with_optional_fields_none(self) -> None:
        """add() без optional fields — None values stored correctly."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        await mem.add(name="minimal")

        session = factory._args[0]
        row = session.added[0]
        assert row.description is None
        assert row.steps is None
        assert row.tenant is None

    @pytest.mark.asyncio
    async def test_add_increments_id_across_calls(self) -> None:
        """Multiple add() calls get incrementing ids."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        id1 = await mem.add(name="sop_1")
        id2 = await mem.add(name="sop_2")
        id3 = await mem.add(name="sop_3")

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3

    @pytest.mark.asyncio
    async def test_add_commits_session(self) -> None:
        """add() вызывает session.commit() и session.refresh()."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        await mem.add(name="x")

        session = factory._args[0]
        assert session.committed, "Session should be committed after add()"


class TestProceduralMemoryRecall:
    """recall() method: SELECT procedural records, ordering by updated_at desc."""

    @pytest.mark.asyncio
    async def test_recall_returns_empty_list_when_no_rows(self) -> None:
        """recall() с пустым store возвращает []."""
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        factory = _make_mock_session_factory([])
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.recall()
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_returns_dict_per_row(self) -> None:
        """recall() возвращает list of dicts с key fields."""
        from src.backend.core.domain.models.langmem_models import LangMemProcedural
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        rows = [
            LangMemProcedural(
                id=1, name="sop1", description="d1", steps={"a": 1},
                updated_at="2024-01-01T10:00:00",
            ),
            LangMemProcedural(
                id=2, name="sop2", description="d2", steps={"b": 2},
                updated_at="2024-01-01T11:00:00",
            ),
        ]
        factory = _make_mock_session_factory(rows)
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.recall()

        assert len(result) == 2
        for d in result:
            assert "id" in d
            assert "name" in d
            assert "description" in d
            assert "steps" in d

    @pytest.mark.asyncio
    async def test_recall_orders_by_updated_at_desc(self) -> None:
        """recall() упорядочивает записи newest first (updated_at desc)."""
        from src.backend.core.domain.models.langmem_models import LangMemProcedural
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        rows = [
            LangMemProcedural(
                id=1, name="oldest", updated_at="2024-01-01T10:00:00"
            ),
            LangMemProcedural(
                id=3, name="newest", updated_at="2024-01-01T12:00:00"
            ),
            LangMemProcedural(
                id=2, name="middle", updated_at="2024-01-01T11:00:00"
            ),
        ]
        factory = _make_mock_session_factory(rows)
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.recall()

        # Ordered newest first.
        assert [d["name"] for d in result] == ["newest", "middle", "oldest"]

    @pytest.mark.asyncio
    async def test_recall_respects_limit(self) -> None:
        """recall(limit=N) возвращает максимум N записей."""
        from src.backend.core.domain.models.langmem_models import LangMemProcedural
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        rows = [
            LangMemProcedural(
                id=i, name=f"sop{i}", updated_at=f"2024-01-01T10:0{i}:00"
            )
            for i in range(5)
        ]
        factory = _make_mock_session_factory(rows)
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.recall(limit=3)

        assert len(result) == 3
        # Newest 3 (ids 4, 3, 2 by updated_at desc).
        assert [d["id"] for d in result] == [4, 3, 2]

    @pytest.mark.asyncio
    async def test_recall_default_limit_is_20(self) -> None:
        """recall() default limit = 20."""
        from src.backend.core.domain.models.langmem_models import LangMemProcedural
        from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

        rows = [
            LangMemProcedural(
                id=i, name=f"sop{i}", updated_at=f"2024-01-01T10:00:0{i}"
            )
            for i in range(25)
        ]
        factory = _make_mock_session_factory(rows)
        mem = ProceduralMemory(session_factory=factory)

        result = await mem.recall()

        # Default limit = 20.
        assert len(result) == 20
