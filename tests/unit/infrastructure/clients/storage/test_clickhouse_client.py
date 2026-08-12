"""Unit-тесты ClickHouseClient — chunking, batch_size override, fail-fast.

Cycle 29 P2: тесты НЕ зависят от optional ``clickhouse_driver`` —
используем только встроенный ``httpx`` путь через ``_ensure_client`` patch.

Sprint 3.6: regression-тесты для ``ping()`` и ``_ensure_client()`` pre-ping —
CH-down сценарий не должен пробрасывать ``httpx.HTTPError`` наружу
(httpx.ConnectError / ConnectTimeout НЕ наследуются от stdlib
ConnectionError/TimeoutError/OSError).
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
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


# ── Sprint 3.6: ping() / pre-ping не должны пробрасывать httpx.HTTPError ──
# ── когда CH down: httpx.ConnectError/ConnectTimeout НЕ являются ──
# ── наследниками (ConnectionError, TimeoutError, OSError) stdlib'а. ──


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectError("connection refused"),
        httpx.ConnectTimeout("connect timeout"),
        httpx.ReadTimeout("read timeout"),
        httpx.PoolTimeout("pool timeout"),
        httpx.ReadError("read error"),
    ],
)
async def test_ping_returns_false_on_httpx_transport_error(exc: Exception) -> None:
    """Sprint 3.6: ping() возвращает False при недоступном CH.

    CH-down → httpx бросает ``httpx.ConnectError``/``ConnectTimeout``/etc.
    Они НЕ наследуются от ``ConnectionError``/``TimeoutError``/``OSError``,
    поэтому except должен включать ``httpx.HTTPError``.
    """
    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.get = AsyncMock(side_effect=exc)
    with patch.object(client, "_ensure_client", return_value=fake_http):
        result = await client.ping()
    assert result is False


@pytest.mark.asyncio
async def test_ensure_client_pre_ping_recreates_pool_on_httpx_error() -> None:
    """Sprint 3.6: _ensure_client pre-ping ловит httpx.HTTPError и recreate'ит пул.

    Раньше except ловил только (ConnectionError, TimeoutError, OSError, RuntimeError)
    и пропускал httpx.ConnectError → propagate'илось в execute/query/insert.
    """
    client = ClickHouseClient(keepalive_expiry=0.0, pool_pre_ping=True)
    # Force pre-ping path: last_used far in the past.
    client._client = AsyncMock()
    client._client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    client._client_created_at = 0.0
    client._last_used_at = 0.0

    close_calls = 0
    original_close = client.close

    async def _track_close() -> None:
        nonlocal close_calls
        close_calls += 1
        await original_close()

    with patch.object(client, "close", side_effect=_track_close):
        with patch.object(client, "connect", new=AsyncMock()) as connect_mock:
            # Should NOT raise — pre-ping failure must be caught.
            await client._ensure_client()
    assert close_calls == 1
    assert connect_mock.await_count == 1


@pytest.mark.asyncio
async def test_ping_does_not_block_when_ch_is_down() -> None:
    """Sprint 3.6: ping() не блокирует production-мониторинг при CH-down.

    Сценарий: HealthAggregator периодически пингует CH. Если CH down и
    ``ping()`` бросает ``httpx.ConnectError`` вместо возврата False,
    HealthAggregator упадёт и положит весь health-probe pipeline.

    После фикса: ping() всегда возвращает bool.
    """
    import asyncio

    client = ClickHouseClient()
    fake_http = AsyncMock()
    fake_http.get = AsyncMock(side_effect=httpx.ConnectError("ECONNREFUSED"))
    with patch.object(client, "_ensure_client", return_value=fake_http):
        # Должен завершиться быстро и без raise.
        result = await asyncio.wait_for(client.ping(), timeout=2.0)
    assert result is False
