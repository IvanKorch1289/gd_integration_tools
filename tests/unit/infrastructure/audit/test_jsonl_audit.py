"""Unit-tests for JsonlAuditBackend."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from src.backend.infrastructure.audit.jsonl_audit import JsonlAuditBackend


@pytest.fixture
def backend(tmp_path: Path) -> JsonlAuditBackend:
    return JsonlAuditBackend(path=tmp_path / "audit.jsonl")


@pytest.mark.asyncio
async def test_append_and_query(backend: JsonlAuditBackend) -> None:
    record = {"who": "alice", "what": "login", "entity_type": "user"}
    await backend.append(record)
    results = await backend.query(limit=10)
    assert len(results) == 1
    assert results[0]["who"] == "alice"
    assert "timestamp" in results[0]


@pytest.mark.asyncio
async def test_query_with_filters(backend: JsonlAuditBackend) -> None:
    await backend.append({"who": "alice", "action": "create"})
    await backend.append({"who": "bob", "action": "delete"})
    results = await backend.query(filters={"who": "alice"})
    assert len(results) == 1
    assert results[0]["who"] == "alice"


@pytest.mark.asyncio
async def test_query_empty_file(backend: JsonlAuditBackend) -> None:
    results = await backend.query()
    assert results == []


@pytest.mark.asyncio
async def test_query_skips_corrupted_lines(backend: JsonlAuditBackend, tmp_path: Path) -> None:
    path = tmp_path / "audit.jsonl"
    path.write_text('{"who":"alice"}\nnot-json\n{"who":"bob"}\n')
    backend = JsonlAuditBackend(path=path)
    results = await backend.query()
    assert len(results) == 2


@pytest.mark.asyncio
async def test_append_with_fsync(tmp_path: Path) -> None:
    backend = JsonlAuditBackend(path=tmp_path / "audit.jsonl", fsync=True)
    await backend.append({"who": "alice"})
    results = await backend.query()
    assert len(results) == 1


@pytest.mark.asyncio
async def test_query_limit(backend: JsonlAuditBackend) -> None:
    for i in range(5):
        await backend.append({"i": i})
    results = await backend.query(limit=2)
    assert len(results) == 2


def test_serialize_adds_timestamp() -> None:
    rec = {"who": "alice"}
    line = JsonlAuditBackend._serialize(rec)
    assert "timestamp" in line


def test_serialize_preserves_existing_timestamp() -> None:
    now = datetime.now(UTC).isoformat()
    rec = {"who": "alice", "timestamp": now}
    line = JsonlAuditBackend._serialize(rec)
    assert now in line
