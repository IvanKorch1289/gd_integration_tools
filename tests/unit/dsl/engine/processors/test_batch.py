"""Unit-тесты batch processors с моком ExternalDatabaseRegistry."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.batch import (
    BatchDeleteProcessor,
    BatchInsertProcessor,
    BatchUpdateProcessor,
)


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body, headers=headers or {}))


@pytest.fixture
def mock_bundle() -> MagicMock:
    bundle = MagicMock()
    session = AsyncMock()
    session.execute = AsyncMock(return_value=MagicMock(rowcount=2))
    session.commit = AsyncMock()
    context_manager = MagicMock()
    context_manager.__aenter__ = AsyncMock(return_value=session)
    context_manager.__aexit__ = AsyncMock(return_value=False)
    bundle.async_session_maker.return_value = context_manager
    return bundle


@pytest.mark.asyncio
async def test_batch_insert(mock_bundle: MagicMock) -> None:
    with patch(
        "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry"
    ) as mock_reg:
        mock_reg.return_value.return_value.get_bundle.return_value = mock_bundle
        proc = BatchInsertProcessor(table="orders", items=[{"id": 1}, {"id": 2}])
        exchange = _ex()
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["batch_insert_result"]["affected"] == 2


@pytest.mark.asyncio
async def test_batch_insert_from_body(mock_bundle: MagicMock) -> None:
    with patch(
        "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry"
    ) as mock_reg:
        mock_reg.return_value.return_value.get_bundle.return_value = mock_bundle
        proc = BatchInsertProcessor(table="orders")
        exchange = _ex([{"id": 1}])
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["batch_insert_result"]["affected"] == 2


@pytest.mark.asyncio
async def test_batch_insert_empty(mock_bundle: MagicMock) -> None:
    proc = BatchInsertProcessor(table="orders", items=[])
    exchange = _ex()
    await proc.process(exchange, None)  # type: ignore[arg-type]
    assert exchange.properties["batch_insert_result"]["affected"] == 0


@pytest.mark.asyncio
async def test_batch_update(mock_bundle: MagicMock) -> None:
    with patch(
        "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry"
    ) as mock_reg:
        mock_reg.return_value.return_value.get_bundle.return_value = mock_bundle
        proc = BatchUpdateProcessor(table="orders", items=[{"id": 1, "status": "ok"}])
        exchange = _ex()
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["batch_update_result"]["affected"] == 2


@pytest.mark.asyncio
async def test_batch_delete(mock_bundle: MagicMock) -> None:
    with patch(
        "src.backend.dsl.engine.processors.batch._lazy_get_external_db_registry"
    ) as mock_reg:
        mock_reg.return_value.return_value.get_bundle.return_value = mock_bundle
        proc = BatchDeleteProcessor(table="orders", ids=[1, 2])
        exchange = _ex()
        await proc.process(exchange, None)  # type: ignore[arg-type]
        assert exchange.properties["batch_delete_result"]["affected"] == 2
