"""Unit-тесты CdcPostgresLogicalSource — Wave [wave:s5/k3-w5-cdc-postgres]."""

# ruff: noqa: S101

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.infrastructure.sources.cdc_postgres_logical import (
    CdcCursorStore,
    CdcPostgresLogicalSource,
)


def test_validates_mode() -> None:
    with pytest.raises(ValueError, match="mode"):
        CdcPostgresLogicalSource("src1", "orders", dsn="postgres://", mode="invalid")


def test_validates_required_args() -> None:
    with pytest.raises(ValueError, match="source_id"):
        CdcPostgresLogicalSource("", "orders", dsn="postgres://")
    with pytest.raises(ValueError, match="table"):
        CdcPostgresLogicalSource("s1", "", dsn="postgres://")
    with pytest.raises(ValueError, match="dsn"):
        CdcPostgresLogicalSource("s1", "orders", dsn="")


def test_default_slot_and_publication() -> None:
    src = CdcPostgresLogicalSource("s1", "orders", dsn="postgres://x")
    assert src.slot_name == "cdc_orders"
    assert src.publication == "pub_orders"


@pytest.mark.asyncio
async def test_setup_runs_publication_and_slot_ddl() -> None:
    executed: list[str] = []

    async def conn_executor(sql: str) -> None:
        executed.append(sql)

    src = CdcPostgresLogicalSource("s1", "orders", dsn="postgres://x")
    await src.setup(conn_executor)
    assert any("CREATE PUBLICATION" in s for s in executed)
    assert any("pg_create_logical_replication_slot" in s for s in executed)


@pytest.mark.asyncio
async def test_start_skipped_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "cdc_postgres_enabled", False)
    src = CdcPostgresLogicalSource("s1", "orders", dsn="postgres://x")
    on_event = AsyncMock()
    await src.start(on_event)
    on_event.assert_not_called()


@pytest.mark.asyncio
async def test_cursor_store_set_get(monkeypatch: pytest.MonkeyPatch) -> None:
    storage: dict[str, str] = {}

    class _FakeSession:
        async def fetchrow(self, sql: str, *args: object) -> dict | None:
            slot = args[0]
            if slot in storage:
                return {"last_lsn": storage[slot]}
            return None

        async def execute(self, sql: str, *args: object) -> None:
            if "INSERT INTO cdc_cursors" in sql:
                storage[args[0]] = args[1]

    @asynccontextmanager
    async def factory():  # type: ignore[no-untyped-def]
        yield _FakeSession()

    store = CdcCursorStore(factory)
    assert await store.get_last_lsn("slot1") is None
    await store.set_last_lsn("slot1", "0/16D5E40")
    assert await store.get_last_lsn("slot1") == "0/16D5E40"


@pytest.mark.asyncio
async def test_full_mode_emits_snapshot_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(feature_flags, "cdc_postgres_enabled", True)
    received = []

    async def on_event(event):  # type: ignore[no-untyped-def]
        received.append(event)

    src = CdcPostgresLogicalSource("s1", "orders", dsn="postgres://x", mode="full")
    # Stub _inner.start, чтобы не подключаться к настоящему PG.
    monkeypatch.setattr(
        "src.backend.infrastructure.sources.cdc.CDCSource.start", AsyncMock()
    )
    await src.start(on_event)
    assert any(e.payload.get("event") == "snapshot_started" for e in received)
