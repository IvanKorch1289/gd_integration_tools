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
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )
        p = InfraClickHouseQueryProcessor(sql="SELECT 1", to="body.result")
        assert p.sql == "SELECT 1"

    @pytest.mark.asyncio
    async def test_executes_clickhouse_query(self) -> None:
        from src.backend.dsl.engine.processors.infra_clickhouse import (
            InfraClickHouseQueryProcessor,
        )
        p = InfraClickHouseQueryProcessor(sql="SELECT count() FROM events", to="body.result")
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
            "src.backend.core.di.providers.infrastructure_facade.get_clickhouse_client_class",
            return_value=ch_class,
        ):
            await p.process(ex, ctx)
        assert body.get("result") == [{"count": 42}]


class TestInfraMongoDBFindProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_mongodb import (
            InfraMongoDBFindProcessor,
        )
        p = InfraMongoDBFindProcessor(collection="users", query={"active": True}, to="body.users")
        assert p.collection == "users"
        assert p.query == {"active": True}

    @pytest.mark.asyncio
    async def test_executes_mongodb_find(self) -> None:
        from src.backend.dsl.engine.processors.infra_mongodb import (
            InfraMongoDBFindProcessor,
        )
        p = InfraMongoDBFindProcessor(collection="users", query={"active": True}, to="body.users")
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
            "src.backend.core.di.providers.infrastructure_facade.get_mongodb_client_class",
            return_value=mongo_class,
        ):
            await p.process(ex, ctx)
        assert body.get("users") == [{"_id": "1", "name": "Alice"}]


class TestInfraKafkaProduceProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_kafka import (
            InfraKafkaProduceProcessor,
        )
        p = InfraKafkaProduceProcessor(topic="orders", value={"order_id": 1})
        assert p.topic == "orders"

    @pytest.mark.asyncio
    async def test_produces_kafka_message(self) -> None:
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
            "src.backend.core.di.providers.infrastructure_facade.get_kafka_producer_class",
            return_value=producer_class,
        ):
            await p.process(ex, ctx)
        producer.send_and_wait.assert_called_once()
