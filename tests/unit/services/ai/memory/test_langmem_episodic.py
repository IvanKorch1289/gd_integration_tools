"""Tests for EpisodicMemory (cycle 64).

Stream E.7 — episodic memory: episodes of dialog/sessions
(role + content + meta + timestamp) stored в Postgres.

Cycle 64 invariant: tests catch regressions in episodic storage
that could lead to silent conversation history corruption.
"""

# ruff: noqa: S101

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

pytestmark = pytest.mark.unit


def _make_mock_session_factory(rows: list[Any]) -> Any:
    """Создаёт async context manager session_factory с given rows.

    Returns session_factory который при вызове возвращает
    session, поддерживающий add() + commit() + refresh() + execute().
    """

    class FakeResult:
        def __init__(self, rows):
            self._rows = rows

        def scalars(self):
            return _FakeScalars(self._rows)

    class _FakeScalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows, store):
            self._rows = rows
            self._store = store  # list[LangMemEpisodic]
            self.added: list = []
            self.committed = False

        def add(self, row):
            # The row passed in is the actual row that add() created.
            # Use it directly (not the rows list).
            self.added.append(row)
            self._rows.append(row)  # also append to rows for recall()
            # Simulate DB auto-increment.
            if getattr(row, "id", None) is None:
                row.id = len(self._rows)

        async def commit(self):
            self.committed = True

        async def refresh(self, row):
            # No-op (row already has attributes).
            pass

        async def execute(self, stmt):
            # stmt is a select() — return rows ordered.
            # Sort by occurred_at desc (default ordering).
            sorted_rows = sorted(
                self._rows, key=lambda r: r.occurred_at, reverse=True
            )
            # Apply limit.
            # Find limit() call result.
            limit_val = stmt._limit if hasattr(stmt, "_limit") else None
            if limit_val is not None:
                sorted_rows = sorted_rows[:limit_val]
            return FakeResult(sorted_rows)

    _args = []

    @asynccontextmanager
    async def factory():
        session = FakeSession(rows, rows)
        _args.append(session)
        yield session

    factory._args = _args  # type: ignore[attr-defined]
    return factory


class TestEpisodicMemoryInit:
    """__init__ stores session_factory."""

    def test_init_stores_session_factory(self) -> None:
        """__init__ stores session_factory parameter."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        factory = MagicMock()
        mem = EpisodicMemory(session_factory=factory)
        assert mem._session_factory is factory


class TestEpisodicMemoryAdd:
    """add() method: insert episode → return id."""

    @pytest.mark.asyncio
    async def test_add_returns_integer_id(self) -> None:
        """add() возвращает integer id из row.id (mock auto-increments)."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        factory = _make_mock_session_factory([])
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.add(session_id="s1", role="user", content="hi")

        # Mock auto-increments: first row gets id=1.
        assert result == 1, f"Expected 1, got {result}"
        assert len(factory._args) == 1  # factory called once

    @pytest.mark.asyncio
    async def test_add_sets_required_fields(self) -> None:
        """add() устанавливает session_id, role, content, occurred_at."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        factory = _make_mock_session_factory([])
        mem = EpisodicMemory(session_factory=factory)

        await mem.add(session_id="abc", role="assistant", content="Hello!")

        # Get the row that add() created and passed to session.add().
        assert len(factory._args) == 1
        session = factory._args[0]
        assert len(session.added) == 1
        row = session.added[0]
        assert row.session_id == "abc"
        assert row.role == "assistant"
        assert row.content == "Hello!"
        # occurred_at should be set to a recent datetime.
        assert row.occurred_at is not None
        # Within last 5 seconds.
        age = (datetime.now(row.occurred_at.tzinfo) - row.occurred_at).total_seconds()
        assert 0 <= age < 5, f"occurred_at should be recent, age={age}"

    @pytest.mark.asyncio
    async def test_add_with_tenant_and_meta(self) -> None:
        """add() сохраняет tenant и meta fields."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        meta_dict = {"source": "test", "tags": ["urgent"]}
        factory = _make_mock_session_factory([])
        mem = EpisodicMemory(session_factory=factory)

        await mem.add(
            session_id="s1",
            role="user",
            content="x",
            tenant="acme",
            meta=meta_dict,
        )

        session = factory._args[0]
        row = session.added[0]
        assert row.tenant == "acme"
        assert row.meta == meta_dict

    @pytest.mark.asyncio
    async def test_add_increments_id_across_calls(self) -> None:
        """Multiple add() calls get incrementing ids (auto-increment)."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        factory = _make_mock_session_factory([])
        mem = EpisodicMemory(session_factory=factory)

        id1 = await mem.add(session_id="s", role="u", content="a")
        id2 = await mem.add(session_id="s", role="u", content="b")
        id3 = await mem.add(session_id="s", role="u", content="c")

        assert id1 == 1
        assert id2 == 2
        assert id3 == 3


class TestEpisodicMemoryRecall:
    """recall() method: SELECT эпизодов, ordering by occurred_at desc."""

    @pytest.mark.asyncio
    async def test_recall_returns_empty_list_when_no_rows(self) -> None:
        """recall() с пустым store возвращает []."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )

        factory = _make_mock_session_factory([])
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()
        assert result == []

    @pytest.mark.asyncio
    async def test_recall_returns_dict_per_row(self) -> None:
        """recall() возвращает list of dicts с key fields."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        ts1 = datetime(2024, 1, 1, 10, 0, 0)
        ts2 = datetime(2024, 1, 1, 11, 0, 0)
        rows = [
            LangMemEpisodic(
                id=1, session_id="s1", role="user", content="first",
                occurred_at=ts1,
            ),
            LangMemEpisodic(
                id=2, session_id="s1", role="assistant", content="second",
                occurred_at=ts2,
            ),
        ]
        factory = _make_mock_session_factory(rows)
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()

        assert len(result) == 2
        # Each result is a dict with expected keys.
        for d in result:
            assert "id" in d
            assert "session_id" in d
            assert "role" in d
            assert "content" in d
            assert "meta" in d
            assert "occurred_at" in d

    @pytest.mark.asyncio
    async def test_recall_orders_by_occurred_at_desc(self) -> None:
        """recall() упорядочивает эпизоды newest first."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        ts1 = datetime(2024, 1, 1, 10, 0, 0)
        ts2 = datetime(2024, 1, 1, 11, 0, 0)
        ts3 = datetime(2024, 1, 1, 12, 0, 0)
        rows = [
            LangMemEpisodic(id=1, session_id="s", role="u", content="oldest", occurred_at=ts1),
            LangMemEpisodic(id=3, session_id="s", role="u", content="newest", occurred_at=ts3),
            LangMemEpisodic(id=2, session_id="s", role="u", content="middle", occurred_at=ts2),
        ]
        factory = _make_mock_session_factory(rows)
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()

        # Ordered newest first.
        assert [d["content"] for d in result] == ["newest", "middle", "oldest"]

    @pytest.mark.asyncio
    async def test_recall_respects_limit(self) -> None:
        """recall(limit=N) возвращает максимум N эпизодов."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        # Create 5 episodes.
        rows = [
            LangMemEpisodic(
                id=i, session_id="s", role="u", content=f"e{i}",
                occurred_at=datetime(2024, 1, 1, 10, i, 0),
            )
            for i in range(5)
        ]
        factory = _make_mock_session_factory(rows)
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall(limit=3)

        # Max 3 episodes returned.
        assert len(result) == 3
        # Newest 3 (ids 4, 3, 2 by occurred_at desc).
        assert [d["id"] for d in result] == [4, 3, 2]

    @pytest.mark.asyncio
    async def test_recall_default_limit_is_20(self) -> None:
        """recall() default limit = 20."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        # Create 25 episodes.
        rows = [
            LangMemEpisodic(
                id=i, session_id="s", role="u", content=f"e{i}",
                occurred_at=datetime(2024, 1, 1, 10, 0, i),
            )
            for i in range(25)
        ]
        factory = _make_mock_session_factory(rows)
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()
        # Default limit = 20.
        assert len(result) == 20

    @pytest.mark.asyncio
    async def test_recall_includes_iso_timestamp(self) -> None:
        """recall() result содержит ISO 8601 timestamp в occurred_at."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        ts = datetime(2024, 6, 15, 14, 30, 0)
        row = LangMemEpisodic(
            id=1, session_id="s", role="u", content="test", occurred_at=ts
        )
        factory = _make_mock_session_factory([row])
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()

        assert result[0]["occurred_at"] is not None
        # ISO format: "2024-06-15T14:30:00+00:00" (UTC).
        assert "2024-06-15" in result[0]["occurred_at"]
        assert "14:30:00" in result[0]["occurred_at"]

    @pytest.mark.asyncio
    async def test_recall_handles_null_occurred_at(self) -> None:
        """recall() с row.occurred_at=None → None в result (defensive)."""
        from src.backend.services.ai.memory.langmem.episodic import (
            EpisodicMemory,
        )
        from src.backend.core.domain.models.langmem_models import (
            LangMemEpisodic,
        )

        # Row with None occurred_at.
        row = LangMemEpisodic(
            id=1, session_id="s", role="u", content="test", occurred_at=None
        )
        factory = _make_mock_session_factory([row])
        mem = EpisodicMemory(session_factory=factory)

        result = await mem.recall()

        # occurred_at is None in result.
        assert result[0]["occurred_at"] is None
