"""Unit-тесты ClickHouseClient — chunking, batch_size override, fail-fast.

Cycle 29 P2: тесты НЕ зависят от optional ``clickhouse_driver`` —
используем только встроенный ``httpx`` путь через ``_ensure_client`` patch.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.infrastructure.clients.storage.clickhouse import (
    MAX_INSERT_ROWS,
    ClickHouseClient,
)

# ── insert(): chunking + batch_size override ────────────────────────


@pytest.mark.asyncio
async def test_insert_chunking_with_default_max_batch_size() -> None:
    """len(rows) > max_batch_size → несколько POST-chunk'ов."""
    client = ClickHouseClient(max_batch_size=2)
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        rows = [{"a": i} for i in range(5)]
        n = await client.insert("events", rows)
    assert n == 5
    # 5 rows / 2 batch_size → 3 chunks (2 + 2 + 1).
    assert fake_http.post.await_count == 3
    for call in fake_http.post.await_args_list:
        query = call.kwargs["params"]["query"]
        assert "INSERT INTO events FORMAT JSONEachRow" in query


@pytest.mark.asyncio
async def test_insert_batch_size_override_reaches_client() -> None:
    """batch_size=2 при дефолтном max_batch_size=10000 → 5 chunks для 10 rows.

    Cycle 29 P2: caller-side ``batch_size`` реально доходит до client
    (а не игнорируется в пользу singleton'овского ``max_batch_size``).
    """
    client = ClickHouseClient(max_batch_size=10_000)
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        rows = [{"a": i} for i in range(10)]
        n = await client.insert("events", rows, batch_size=2)
    assert n == 10
    # 10 rows / 2 batch_size → ровно 5 chunks.
    assert fake_http.post.await_count == 5


@pytest.mark.asyncio
async def test_insert_empty_rows_no_http_call() -> None:
    """Пустой список → 0 без обращения к HTTP."""
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        n = await client.insert("events", [])
    assert n == 0
    fake_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_insert_invalid_batch_size_raises() -> None:
    """batch_size <= 0 → ValueError до HTTP-вызова."""
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        with pytest.raises(ValueError, match="batch_size must be > 0"):
            await client.insert("events", [{"a": 1}], batch_size=0)
        with pytest.raises(ValueError, match="batch_size must be > 0"):
            await client.insert("events", [{"a": 1}], batch_size=-5)
    fake_http.post.assert_not_awaited()


# ── insert(): fail-fast на oversized batch ──────────────────────────


@pytest.mark.asyncio
async def test_insert_fails_fast_on_oversized_batch() -> None:
    """len(rows) > MAX_INSERT_ROWS → ValueError до первого POST.

    Cycle 29 P2: защита от OOM / runaway-ETL.
    """
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    rows = [{"a": i} for i in range(MAX_INSERT_ROWS + 1)]
    with patch.object(client, "_ensure_client", return_value=fake_http):
        with pytest.raises(ValueError, match="oversized batch"):
            await client.insert("events", rows)
    fake_http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_insert_accepts_exactly_max_insert_rows() -> None:
    """Граничный кейс: ровно MAX_INSERT_ROWS — должно пройти (без вызова POST
    мокаем с max_batch_size=MAX_INSERT_ROWS, чтобы получить 1 chunk).
    """
    client = ClickHouseClient(max_batch_size=MAX_INSERT_ROWS)
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    rows = [{"a": i} for i in range(MAX_INSERT_ROWS)]
    with patch.object(client, "_ensure_client", return_value=fake_http):
        n = await client.insert("events", rows)
    assert n == MAX_INSERT_ROWS
    assert fake_http.post.await_count == 1


# ── chunking invariants ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_chunking_covers_all_rows_without_duplicates() -> None:
    """Cycle 29 P2: каждый row попадает ровно в один chunk.

    Без optional driver — проверяем через размер chunk'ов в POST-content.
    """
    import orjson

    client = ClickHouseClient(max_batch_size=3)
    fake_http = AsyncMock()
    fake_http.post = AsyncMock(return_value=MagicMock(status_code=200))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        rows = [{"id": i} for i in range(10)]  # 10 / 3 → 4 chunks (3+3+3+1)
        n = await client.insert("events", rows)
    assert n == 10
    assert fake_http.post.await_count == 4
    seen_ids: set[int] = set()
    for call in fake_http.post.await_args_list:
        body = call.kwargs["content"].decode()
        for line in body.split("\n"):
            if not line:
                continue
            row = orjson.loads(line)
            seen_ids.add(row["id"])
    assert seen_ids == set(range(10))
