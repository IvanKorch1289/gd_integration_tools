"""Tests for Facade → DSL processors (Sprint 170 M2 Phase 2).

Pattern: DSL processor lazy-imports facade provider, calls it, returns result to Exchange.
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFacadeGetHealthProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.facade_get_health import (
            FacadeGetHealthProcessor,
        )
        p = FacadeGetHealthProcessor(name="redis", to="body.health")
        assert p.component_name == "redis"
        assert p.target == "body.health"

    @pytest.mark.asyncio
    async def test_returns_status_from_health(self) -> None:
        from src.backend.dsl.engine.processors.facade_get_health import (
            FacadeGetHealthProcessor,
        )
        p = FacadeGetHealthProcessor(name="redis", to="body.health")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock the facade provider
        health_fn = AsyncMock(return_value={"status": "ok", "latency_ms": 1.0, "error": None})
        with patch(
            "src.backend.core.di.providers.infrastructure_facade.get_health_check_factory",
            return_value=MagicMock(return_value=health_fn),
        ):
            await p.process(ex, ctx)
        assert body.get("health") == {"status": "ok", "latency_ms": 1.0, "error": None}


class TestInfraS3GetProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor
        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        assert p.key == "test/file.json"

    @pytest.mark.asyncio
    async def test_reads_s3_object(self) -> None:
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor
        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Patch get_object_storage_class at module level
        storage_instance = MagicMock()
        storage_instance.get = AsyncMock(return_value=b'{"data": 1}')
        storage_class = MagicMock(return_value=storage_instance)
        with patch(
            "src.backend.core.di.providers.infrastructure_facade.get_object_storage_class",
            return_value=storage_class,
        ):
            await p.process(ex, ctx)
        assert body.get("content") == b'{"data": 1}'


class TestInfraRedisGetProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_redis import InfraRedisGetProcessor
        p = InfraRedisGetProcessor(key="cache:counter", to="body.value")
        assert p.key == "cache:counter"

    @pytest.mark.asyncio
    async def test_reads_redis_value(self) -> None:
        from src.backend.dsl.engine.processors.infra_redis import InfraRedisGetProcessor
        p = InfraRedisGetProcessor(key="cache:counter", to="body.value")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Use dict-like access (Redis returns dict, not async for some impls)
        # Try with AsyncMock
        client_instance = MagicMock()
        client_instance.get = AsyncMock(return_value="42")
        client_class = MagicMock(return_value=client_instance)
        with patch(
            "src.backend.core.di.providers.infrastructure_facade.get_redis_client_class",
            return_value=client_class,
        ):
            await p.process(ex, ctx)
        assert body.get("value") == "42"


class TestInfraLogWriteProcessor:
    @pytest.mark.asyncio
    async def test_processor_validates_level(self) -> None:
        from src.backend.dsl.engine.processors.infra_log import InfraLogWriteProcessor
        with pytest.raises(ValueError):
            InfraLogWriteProcessor(level="invalid", message="test")

    @pytest.mark.asyncio
    async def test_processor_accepts_valid_level(self) -> None:
        from src.backend.dsl.engine.processors.infra_log import InfraLogWriteProcessor
        p = InfraLogWriteProcessor(level="info", message="hello world")
        assert p.level == "info"
        assert p.message == "hello world"

    @pytest.mark.asyncio
    async def test_writes_log_message(self) -> None:
        from src.backend.dsl.engine.processors.infra_log import InfraLogWriteProcessor
        p = InfraLogWriteProcessor(level="info", message="hello world")
        ex = MagicMock()
        ctx = MagicMock()
        with patch("src.backend.core.logging.get_logger") as mock_logger:
            logger = MagicMock()
            logger.info = MagicMock()
            mock_logger.return_value = logger
            await p.process(ex, ctx)
            logger.info.assert_called_once_with("hello world")


class TestInfraDbQueryProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor
        p = InfraDbQueryProcessor(sql="SELECT 1", to="body.result")
        assert p.sql == "SELECT 1"

    @pytest.mark.asyncio
    async def test_executes_sql_query(self) -> None:
        from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor
        p = InfraDbQueryProcessor(sql="SELECT 1", to="body.result")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock session manager
        session = MagicMock()
        session.execute = AsyncMock(return_value=[{"?column?": 1}])
        sm = MagicMock()
        sm.session = MagicMock()
        sm.session.return_value.__aenter__ = AsyncMock(return_value=session)
        sm.session.return_value.__aexit__ = AsyncMock(return_value=None)
        get_sm = MagicMock(return_value=sm)
        with patch(
            "src.backend.core.di.providers.infrastructure_facade.get_main_session_manager_getter",
            return_value=get_sm,
        ):
            await p.process(ex, ctx)
        assert body.get("result") == [{"?column?": 1}]
