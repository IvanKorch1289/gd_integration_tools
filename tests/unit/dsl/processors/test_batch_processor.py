"""Unit tests for src.backend.dsl.processors.batch_processor (K3 W3b, S39).

Subagent #1 created batch_processor.py but timed out before test creation.
Orchestrator завершил.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.processors.batch_processor import BatchProcessor


class _FakeRow(dict):
    """Row-like dict for tests."""


class _MockSessionCtx:
    def __init__(self, session: Any) -> None:
        self.session = session

    async def __aenter__(self) -> Any:
        return self.session

    async def __aexit__(self, *_args: Any) -> None:
        return None


def _make_exchange(rows: Any = None) -> Exchange:
    msg = Message(body=rows if rows is not None else [], headers={})
    return Exchange(in_message=msg, out_message=msg)


def _make_model() -> Any:
    m = MagicMock()
    m.__name__ = "TestModel"
    return m


def _make_session() -> Any:
    sess = MagicMock()
    sess.bulk_insert_mappings = MagicMock()
    sess.bulk_update_mappings = MagicMock()
    sess.commit = AsyncMock()
    sess.execute = AsyncMock()
    sess.run_sync = AsyncMock()
    return sess


class TestBatchInit:
    def test_init_insert(self) -> None:
        m = _make_model()
        p = BatchProcessor(mode="insert", model=m, batch_size=50)
        assert p._mode == "insert"
        assert p._batch_size == 50

    def test_init_invalid_mode_raises(self) -> None:
        m = _make_model()
        with pytest.raises(ValueError, match="mode"):
            BatchProcessor(mode="upsert", model=m)

    def test_init_invalid_batch_size_raises(self) -> None:
        m = _make_model()
        with pytest.raises(ValueError, match="batch_size"):
            BatchProcessor(mode="insert", model=m, batch_size=0)

    def test_init_default_batch_size(self) -> None:
        p = BatchProcessor(mode="insert", model=_make_model())
        assert p._batch_size == 100


class TestBatchInsert:
    async def test_insert_basic(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="insert", model=model, batch_size=10, session_provider=provider
        )
        ex = _make_exchange([{"id": 1}, {"id": 2}, {"id": 3}])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_insert_result")
        assert result["processed"] == 3
        assert result["batches"] == 1

    async def test_insert_with_size_split(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="insert", model=model, batch_size=100, session_provider=provider
        )
        rows = [{"id": i} for i in range(250)]
        ex = _make_exchange(rows)
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_insert_result")
        assert result["processed"] == 250
        assert result["total_batches"] == 3  # 100 + 100 + 50

    async def test_insert_empty(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(mode="insert", model=model, session_provider=provider)
        ex = _make_exchange([])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_insert_result")
        assert result["processed"] == 0
        assert result["batches"] == 0

    async def test_insert_idempotent_skip_duplicate(self) -> None:
        """IntegrityError on batch → batch skipped, others commit."""
        model = _make_model()
        sess = _make_session()

        # First call raises IntegrityError, second succeeds
        call_count = [0]

        async def fake_run_sync(_fn: Any) -> None:
            call_count[0] += 1
            if call_count[0] == 1:
                from sqlalchemy.exc import IntegrityError

                raise IntegrityError("dup", params={}, orig=Exception("dup"))

        sess.run_sync = fake_run_sync
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="insert", model=model, batch_size=2, session_provider=provider
        )
        ex = _make_exchange([{"id": 1}, {"id": 2}, {"id": 3}, {"id": 4}])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_insert_result")
        # 2 batches: 1 failed (skipped), 1 succeeded
        assert result["batches"] == 1  # Only successful batch counted
        assert result["total_batches"] == 2  # Total attempted


class TestBatchUpdate:
    async def test_update_basic(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="update", model=model, batch_size=10, session_provider=provider
        )
        ex = _make_exchange([{"id": 1, "name": "x"}])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_update_result")
        assert result["processed"] == 1


class TestBatchDelete:
    async def test_delete_basic(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="delete", model=model, batch_size=10, session_provider=provider
        )
        ex = _make_exchange([{"id": 1}, {"id": 2}])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_delete_result")
        assert result["processed"] == 2

    async def test_delete_chunks(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="delete", model=model, batch_size=3, session_provider=provider
        )
        rows = [{"id": i} for i in range(10)]
        ex = _make_exchange(rows)
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_delete_result")
        assert result["total_batches"] == 4  # 3 + 3 + 3 + 1


class TestBatchSourceField:
    async def test_custom_source_field(self) -> None:
        model = _make_model()
        sess = _make_session()
        provider = MagicMock(return_value=_MockSessionCtx(sess))
        p = BatchProcessor(
            mode="insert", model=model, source_field="data", session_provider=provider
        )
        ex = _make_exchange()
        ex.set_property("data", [{"id": 1}])
        await p.process(ex, context=MagicMock())
        result = ex.get_property("batch_insert_result")
        assert result["source_field"] == "data"


class TestBatchToSpec:
    def test_to_spec(self) -> None:
        p = BatchProcessor(
            mode="insert", model=_make_model(), batch_size=50, source_field="rows"
        )
        spec = p.to_spec()
        assert spec is not None
        assert spec["batch"]["mode"] == "insert"
        assert spec["batch"]["batch_size"] == 50
        assert spec["batch"]["source_field"] == "rows"
