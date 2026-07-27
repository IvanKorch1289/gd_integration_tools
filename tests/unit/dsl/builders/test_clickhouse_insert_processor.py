# ruff: noqa: S101
"""Unit-тесты ``ClickHouseInsertProcessor`` — Cycle 29 P2 batch contract.

Покрывает:

* rows берутся из ``exchange.in_message.body`` (``rows_from="body"`` по умолчанию);
* ``batch_size`` пробрасывается в ``client.insert(batch_size=...)``;
* dotted-path ``rows_from="body.rows"`` спускается во вложенный список;
* oversized body (>``MAX_INSERT_ROWS``) → ``exchange.fail(...)`` без HTTP;
* ``rows_from`` с невалидным путём → ``exchange.fail(...)`` без HTTP;
* пустой список → 0 без обращения к client.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.backend.dsl.builders.infrastructure_dsl import ClickHouseInsertProcessor
from src.backend.infrastructure.clients.storage.clickhouse import MAX_INSERT_ROWS


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(self, body: Any = None) -> None:
        self.in_message = _Message(body=body)
        self.properties: dict[str, Any] = {}
        self._error: str | None = None

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value

    def fail(self, msg: str) -> None:
        self._error = msg


class _Context:
    pass


@pytest.mark.asyncio
class TestRowsFromBody:
    async def test_rows_taken_from_body_by_default(self) -> None:
        rows = [{"a": 1}, {"a": 2}]
        exchange = _Exchange(body=rows)
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock(return_value=2)
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events", batch_size=10)
            await proc.process(exchange, _Context())
        # Rows попали в client.insert из body.
        call_kwargs = mock_client.insert.await_args.kwargs
        assert mock_client.insert.await_args.args[0] == "events"
        assert mock_client.insert.await_args.args[1] == rows
        assert call_kwargs["batch_size"] == 10
        assert exchange.properties["clickhouse_insert_result"] == 2
        assert exchange._error is None

    async def test_rows_taken_from_dotted_path(self) -> None:
        body = {"rows": [{"a": 1}, {"a": 2}, {"a": 3}], "meta": "x"}
        exchange = _Exchange(body=body)
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock(return_value=3)
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(
                table="events", batch_size=5, rows_from="body.rows"
            )
            await proc.process(exchange, _Context())
        call_args = mock_client.insert.await_args
        assert call_args.args[1] == [{"a": 1}, {"a": 2}, {"a": 3}]
        assert call_args.kwargs["batch_size"] == 5
        assert exchange.properties["clickhouse_insert_result"] == 3

    async def test_empty_list_no_http(self) -> None:
        exchange = _Exchange(body=[])
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock(return_value=0)
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events", batch_size=10)
            await proc.process(exchange, _Context())
        mock_client.insert.assert_awaited_once_with("events", [], batch_size=10)
        assert exchange.properties["clickhouse_insert_result"] == 0
        assert exchange._error is None


@pytest.mark.asyncio
class TestBatchSizeReachesClient:
    async def test_batch_size_passed_through(self) -> None:
        """Cycle 29 P2: ``batch_size`` реально доходит до client.insert()."""
        rows = [{"a": i} for i in range(3)]
        exchange = _Exchange(body=rows)
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock(return_value=3)
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events", batch_size=5000)
            await proc.process(exchange, _Context())
        # Проверяем что batch_size=5000 пробрасывается, а не дефолт 1000.
        assert mock_client.insert.await_args.kwargs["batch_size"] == 5000

    async def test_no_batch_size_passed_when_unset(self) -> None:
        """Если batch_size=None — caller-side override выключен."""
        rows = [{"a": 1}]
        exchange = _Exchange(body=rows)
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock(return_value=1)
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events")  # no batch_size
            await proc.process(exchange, _Context())
        assert mock_client.insert.await_args.kwargs["batch_size"] is None


@pytest.mark.asyncio
class TestFailFastOnOversized:
    async def test_oversized_body_fails_fast(self) -> None:
        """Cycle 29 P2: len(rows) > MAX_INSERT_ROWS → exchange.fail() без HTTP."""
        rows = [{"a": i} for i in range(MAX_INSERT_ROWS + 1)]
        exchange = _Exchange(body=rows)
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock()
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events", batch_size=1000)
            await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "oversized batch" in exchange._error
        assert str(MAX_INSERT_ROWS) in exchange._error
        # Клиент не вызван.
        mock_client.insert.assert_not_awaited()
        # И result-property не выставлен (pipeline видит fail).
        assert "clickhouse_insert_result" not in exchange.properties


@pytest.mark.asyncio
class TestFailFastOnBadPath:
    async def test_missing_body_property_fails(self) -> None:
        exchange = _Exchange(body={"other": []})
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock()
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(
                table="events", batch_size=10, rows_from="body.rows"
            )
            await proc.process(exchange, _Context())
        assert exchange._error is not None
        assert "missing" in exchange._error or "rows_from" in exchange._error
        mock_client.insert.assert_not_awaited()

    async def test_non_dict_row_fails(self) -> None:
        """list, но элемент — не dict: rows не подходят для JSONEachRow."""
        exchange = _Exchange(body=["not-a-dict"])
        mock_client = AsyncMock()
        mock_client.insert = AsyncMock()
        with patch(
            "src.backend.infrastructure.clients.storage.clickhouse.get_clickhouse_client",
            return_value=mock_client,
        ):
            proc = ClickHouseInsertProcessor(table="events", batch_size=10)
            await proc.process(exchange, _Context())
        assert exchange._error is not None
        mock_client.insert.assert_not_awaited()
