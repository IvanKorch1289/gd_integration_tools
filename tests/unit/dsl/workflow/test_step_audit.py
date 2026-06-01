"""Unit-тесты StepAuditMiddleware — Wave [wave:s5/k3-w11-step-log-clickhouse]."""

# ruff: noqa: S101

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.infrastructure.workflow.middlewares.step_audit import (
    PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL,
    StepAuditMiddleware,
    schema_hash,
)


@pytest.fixture(autouse=True)
def _enable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "workflow_step_log_enabled", True)


@pytest.mark.asyncio
async def test_track_step_buffers_event() -> None:
    fake_client = MagicMock()
    fake_client.insert = AsyncMock()
    mw = StepAuditMiddleware(clickhouse_client=fake_client, batch_size=10)
    await mw.start()
    try:
        async with mw.track_step(
            workflow_id="wf1", step_name="fetch", correlation_id="cid-1"
        ) as ctx:
            ctx.input_schema_hash = "abc"
            ctx.output_schema_hash = "def"
        # Buffer теперь содержит 1 event
        assert len(mw._buffer) == 1
        e = mw._buffer[0]
        assert e.workflow_id == "wf1"
        assert e.step_name == "fetch"
        assert e.input_schema_hash == "abc"
        assert e.status == "ok"
    finally:
        await mw.stop()


def test_schema_hash_deterministic() -> None:
    h1 = schema_hash({"a": 1, "b": 2})
    h2 = schema_hash({"a": 1, "b": 2})
    h3 = schema_hash({"a": 1, "b": 3})
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex


@pytest.mark.asyncio
async def test_otel_attrs_swallowed_when_no_otel() -> None:
    """Если OTel недоступен — middleware не должен падать."""
    mw = StepAuditMiddleware(clickhouse_client=None)
    # Без OTel-интеграции в окружении тест должен пройти.
    mw._set_otel_attrs(step_name="x", duration_ms=10.0, status="ok")


@pytest.mark.asyncio
async def test_batch_size_triggers_flush() -> None:
    fake_client = MagicMock()
    fake_client.insert = AsyncMock()
    mw = StepAuditMiddleware(clickhouse_client=fake_client, batch_size=2)
    await mw.start()
    try:
        for i in range(2):
            async with mw.track_step(workflow_id=f"wf{i}", step_name="s") as ctx:
                ctx.input_schema_hash = "h"
        # Дожидаемся фоновых tasks
        await asyncio.sleep(0.1)
        # После batch_size events insert вызван
        assert fake_client.insert.await_count >= 1
    finally:
        await mw.stop()


@pytest.mark.asyncio
async def test_error_during_step_marked_status_error() -> None:
    mw = StepAuditMiddleware(clickhouse_client=None)
    await mw.start()
    try:
        with pytest.raises(ValueError):
            async with mw.track_step(workflow_id="wf1", step_name="bad"):
                raise ValueError("boom")
        assert mw._buffer[-1].status == "error"
    finally:
        await mw.stop()


def test_ddl_present() -> None:
    assert "CREATE TABLE" in PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL
    assert "workflow_step_log" in PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL
    assert "MergeTree" in PG_CLICKHOUSE_WORKFLOW_STEP_LOG_DDL
