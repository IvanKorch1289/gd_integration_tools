"""Тесты ``JsonlAuditBackend`` (Wave 21.3c)."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.audit import AuditRecord
from src.backend.infrastructure.audit.jsonl_audit import JsonlAuditBackend


@pytest.mark.asyncio
async def test_append_then_query_returns_record(tmp_path):
    backend = JsonlAuditBackend(tmp_path / "audit.jsonl")
    await backend.append(AuditRecord({"event": "user.login", "actor": "u-1"}))
    records = await backend.query(limit=10)
    assert len(records) == 1
    assert records[0]["event"] == "user.login"
    assert records[0]["actor"] == "u-1"
    assert "timestamp" in records[0]  # авто-проставляется


@pytest.mark.asyncio
async def test_append_preserves_explicit_timestamp(tmp_path):
    backend = JsonlAuditBackend(tmp_path / "audit.jsonl")
    await backend.append(
        AuditRecord({"event": "x", "timestamp": "2026-01-01T00:00:00+00:00"})
    )
    records = await backend.query()
    assert records[0]["timestamp"] == "2026-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_query_respects_limit(tmp_path):
    backend = JsonlAuditBackend(tmp_path / "audit.jsonl")
    for i in range(5):
        await backend.append(AuditRecord({"event": "e", "i": i}))
    records = await backend.query(limit=3)
    assert len(records) == 3
    # Хвост: последние 3 записи (i=2,3,4).
    assert [r["i"] for r in records] == [2, 3, 4]


@pytest.mark.asyncio
async def test_query_filters_by_field(tmp_path):
    backend = JsonlAuditBackend(tmp_path / "audit.jsonl")
    await backend.append(AuditRecord({"event": "login", "actor": "u-1"}))
    await backend.append(AuditRecord({"event": "logout", "actor": "u-1"}))
    await backend.append(AuditRecord({"event": "login", "actor": "u-2"}))
    records = await backend.query(filters={"event": "login"})
    assert len(records) == 2
    assert {r["actor"] for r in records} == {"u-1", "u-2"}


@pytest.mark.asyncio
async def test_query_returns_empty_when_no_file(tmp_path):
    backend = JsonlAuditBackend(tmp_path / "missing.jsonl")
    assert await backend.query() == []


@pytest.mark.asyncio
async def test_corrupt_lines_skipped(tmp_path):
    path = tmp_path / "audit.jsonl"
    backend = JsonlAuditBackend(path)
    await backend.append(AuditRecord({"event": "good"}))
    # Дописываем повреждённую строку напрямую.
    path.open("a", encoding="utf-8").write("not-json-at-all\n")
    await backend.append(AuditRecord({"event": "good2"}))
    records = await backend.query()
    assert [r["event"] for r in records] == ["good", "good2"]
