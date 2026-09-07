"""Тесты InfraMongoDBFindProcessor (T3 ratchet: infra_mongodb.py 0→100%).

process: DI client -> client[collection].find(query) -> set_result(to).
Клиент патчится через инфраструктурный провайдер.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.infra_mongodb import InfraMongoDBFindProcessor


def _processor() -> InfraMongoDBFindProcessor:
    return InfraMongoDBFindProcessor(collection="users", query={"active": True})


def _exchange() -> Exchange[Any]:
    exchange = MagicMock(spec=["set_property", "in_message", "fail"])
    exchange.in_message = SimpleNamespace(body={})
    return exchange


def _context() -> ExecutionContext:
    return MagicMock(spec=["trace_id"])


@pytest.mark.asyncio
async def test_process_queries_collection_and_sets_result() -> None:
    proc = _processor()
    exchange = _exchange()
    coll = AsyncMock()
    coll.find = AsyncMock(return_value=[{"u": 1}, {"u": 2}])
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=coll)

    with (
        patch(
            "src.backend.core.di.providers.infrastructure_locator.get_mongodb_client_class",
            return_value=lambda ctx: client,
        ),
        patch.object(proc, "set_result") as mock_set_result,
    ):
        await proc.process(exchange, _context())

    coll.find.assert_awaited_once_with({"active": True})
    mock_set_result.assert_called_once_with(exchange, "body.result", [{"u": 1}, {"u": 2}])


@pytest.mark.asyncio
async def test_process_empty_query_uses_empty_filter() -> None:
    proc = InfraMongoDBFindProcessor(collection="users")
    exchange = _exchange()
    coll = AsyncMock()
    coll.find = AsyncMock(return_value=[])
    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=coll)

    with (
        patch(
            "src.backend.core.di.providers.infrastructure_locator.get_mongodb_client_class",
            return_value=lambda ctx: client,
        ),
        patch.object(proc, "set_result") as mock_set_result,
    ):
        await proc.process(exchange, _context())

    coll.find.assert_awaited_once_with({})
    mock_set_result.assert_called_once_with(exchange, "body.result", [])


def test_processor_metadata() -> None:
    proc = _processor()
    assert proc.name == "infra_mongodb_find:users"
    assert proc.collection == "users"
    assert proc.query == {"active": True}
    assert proc.target == "body.result"
