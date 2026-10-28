"""Tests for gap-fill DSL processors (Sprint 170 M2 Phase 3).

New processors for infra categories that lacked DSL:
- infra_clickhouse_query: ClickHouse analytical queries
- infra_mongodb_find: MongoDB document queries
- infra_kafka_produce: Kafka message production
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestInfraClickHouseQueryProcessor:
    """Тесты процессора аналитического ClickHouse-запроса."""

    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        """Проверяет создание процессора."""
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )

        p = InfraClickHouseQueryProcessor(sql="SELECT 1", to="body.result")
        assert p.sql == "SELECT 1"

    @pytest.mark.asyncio
    async def test_executes_clickhouse_query(self) -> None:
        """Проверяет выполнение SELECT через ClickHouse-клиент."""
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )

        sql = "SELECT count() FROM events"
        p = InfraClickHouseQueryProcessor(sql=sql, to="body.result")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock ClickHouseClient.query
        client = MagicMock()
        client.query = AsyncMock(return_value=[{"count": 42}])
        ch_class = MagicMock(return_value=client)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_clickhouse_client_class",
            return_value=ch_class,
        ):
            await p.process(ex, ctx)
        assert body.get("result") == [{"count": 42}]
        client.query.assert_awaited_once_with(sql)

    @pytest.mark.asyncio
    async def test_rejects_ddl_without_querying_clickhouse(self) -> None:
        """DDL отклоняется до обращения к ClickHouse."""
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )

        p = InfraClickHouseQueryProcessor(sql="DROP TABLE events")
        ex = MagicMock()
        ctx = MagicMock()
        client = MagicMock()
        client.query = AsyncMock()
        ch_class = MagicMock(return_value=client)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_clickhouse_client_class",
            return_value=ch_class,
        ):
            await p.process(ex, ctx)

        ex.fail.assert_called_once_with(
            "SQL validation failed: SQL command 'DROP' is not allowed"
        )
        ch_class.assert_not_called()
        client.query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_rejects_multi_statement_without_querying_clickhouse(self) -> None:
        """Multi-statement отклоняется до обращения к ClickHouse."""
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )

        p = InfraClickHouseQueryProcessor(sql="SELECT 1; SELECT 2")
        ex = MagicMock()
        ctx = MagicMock()
        client = MagicMock()
        client.query = AsyncMock()
        ch_class = MagicMock(return_value=client)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_clickhouse_client_class",
            return_value=ch_class,
        ):
            await p.process(ex, ctx)

        ex.fail.assert_called_once_with(
            "SQL validation failed: Multi-statement SQL is not allowed"
        )
        ch_class.assert_not_called()
        client.query.assert_not_awaited()


class TestInfraMongoDBFindProcessor:
    """Тесты процессора поиска документов MongoDB."""

    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        """Проверяет создание процессора."""
        from src.backend.dsl.engine.processors.infra_mongodb import (
            InfraMongoDBFindProcessor,
        )

        p = InfraMongoDBFindProcessor(
            collection="users", query={"active": True}, to="body.users"
        )
        assert p.collection == "users"
        assert p.query == {"active": True}

    @pytest.mark.asyncio
    async def test_executes_mongodb_find(self) -> None:
        """Проверяет выполнение поиска через MongoDB-клиент."""
        from src.backend.dsl.engine.processors.infra_mongodb import (
            InfraMongoDBFindProcessor,
        )

        p = InfraMongoDBFindProcessor(
            collection="users", query={"active": True}, to="body.users"
        )
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock MongoDBClient
        coll = MagicMock()
        coll.find = AsyncMock(return_value=[{"_id": "1", "name": "Alice"}])
        client = MagicMock()
        client.__getitem__ = MagicMock(return_value=coll)
        mongo_class = MagicMock(return_value=client)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_mongodb_client_class",
            return_value=mongo_class,
        ):
            await p.process(ex, ctx)
        assert body.get("users") == [{"_id": "1", "name": "Alice"}]


class TestInfraKafkaProduceProcessor:
    """Тесты процессора отправки сообщения в Kafka."""

    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        """Проверяет создание процессора."""
        from src.backend.dsl.engine.processors.infra_kafka import (
            InfraKafkaProduceProcessor,
        )

        p = InfraKafkaProduceProcessor(topic="orders", value={"order_id": 1})
        assert p.topic == "orders"

    @pytest.mark.asyncio
    async def test_produces_kafka_message(self) -> None:
        """Проверяет отправку сообщения через Kafka-продюсер."""
        from src.backend.dsl.engine.processors.infra_kafka import (
            InfraKafkaProduceProcessor,
        )

        p = InfraKafkaProduceProcessor(topic="orders", value={"order_id": 1})
        ex = MagicMock()
        ctx = MagicMock()
        # Mock producer
        producer = MagicMock()
        producer.send_and_wait = AsyncMock()
        producer_class = MagicMock(return_value=producer)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_kafka_producer_class",
            return_value=producer_class,
        ):
            await p.process(ex, ctx)
        producer.send_and_wait.assert_called_once()
