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
        health_fn = AsyncMock(
            return_value={"status": "ok", "latency_ms": 1.0, "error": None}
        )
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_health_check_factory",
            return_value=MagicMock(return_value=health_fn),
        ):
            await p.process(ex, ctx)
        assert body.get("health") == {"status": "ok", "latency_ms": 1.0, "error": None}

    @pytest.mark.asyncio
    async def test_health_bridge_uses_canonical_aggregator(self) -> None:
        from src.backend.infrastructure.application.health_aggregator import (
            get_health_aggregator,
        )
        from src.backend.infrastructure.di_bridge.health import get_health_check_factory

        aggregator = get_health_aggregator()

        async def check() -> dict[str, str]:
            return {"status": "ok"}

        aggregator.register("bridge-test", check)
        try:
            result = await get_health_check_factory()("bridge-test")()
        finally:
            aggregator.unregister("bridge-test")

        assert result["status"] == "ok"


class TestInfraS3GetProcessor:
    @pytest.mark.asyncio
    async def test_processor_exists(self) -> None:
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor

        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        assert p.key == "test/file.json"

    @pytest.mark.asyncio
    async def test_reads_s3_object(self) -> None:
        """infra_s3_get скачивает объект через StorageFacade."""
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor
        from src.backend.services.storage.facade import StorageFacade

        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        storage_instance = MagicMock()
        storage_instance.download = AsyncMock(return_value=b'{"data": 1}')
        facade = StorageFacade(storage=storage_instance, plugin="route-1")
        with patch(
            "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
            return_value=facade,
        ):
            await p.process(ex, ctx)
        assert body.get("content") == b'{"data": 1}'

    @pytest.mark.asyncio
    async def test_goes_through_facade_and_checks_read_capability(self) -> None:
        """Шаг идёт через фасад → ``_assert_read`` вызывается (storage.read)."""
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor
        from src.backend.services.storage.facade import StorageFacade

        checks: list[tuple[str, str, str | None]] = []
        storage_instance = MagicMock()
        storage_instance.download = AsyncMock(return_value=b"payload")

        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        facade = StorageFacade(
            storage=storage_instance,
            capability_check=lambda plugin, cap, scope: checks.append(
                (plugin, cap, scope)
            ),
            plugin="route-1",
        )
        with patch(
            "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
            return_value=facade,
        ):
            await p.process(ex, ctx)

        assert checks == [("route-1", "storage.read", "test/file.json")]
        assert body.get("content") == b"payload"

    @pytest.mark.asyncio
    async def test_capability_gate_from_registry_is_used(self) -> None:
        """CapabilityGate из svcs_registry проверяет storage.read.<key>."""
        from src.backend.core.security.capabilities.gate import CapabilityGate
        from src.backend.dsl.engine.context import ExecutionContext
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor

        calls: list[tuple[str, str, str | None]] = []

        class _Gate:
            """Минимальный stand-in CapabilityGate (только ``check``)."""

            def check(self, plugin: str, capability: str, scope: str | None) -> None:
                calls.append((plugin, capability, scope))

        storage_instance = MagicMock()
        storage_instance.download = AsyncMock(return_value=b"payload")

        p = InfraS3GetProcessor(key="test/file.json", to="body.content")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = ExecutionContext(route_id="route-1")

        def _has_service(key: object) -> bool:
            # StorageFacade в реестре не зарегистрирован → fallback-путь
            # резолвера фасада (DI-provider + gate из реестра).
            return key is CapabilityGate

        with (
            patch(
                "src.backend.core.svcs_registry.has_service", side_effect=_has_service
            ),
            patch("src.backend.core.svcs_registry.get_service", return_value=_Gate()),
            patch(
                "src.backend.core.di.providers.cache.get_object_storage_provider",
                return_value=storage_instance,
            ),
        ):
            await p.process(ex, ctx)

        assert calls == [("route-1", "storage.read", "test/file.json")]
        assert body.get("content") == b"payload"


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
            "src.backend.core.di.providers.infrastructure_locator.get_redis_client_class",
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
    async def test_executes_sql_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from src.backend.core.config.features import feature_flags
        from src.backend.dsl.engine.processors.infra_db import InfraDbQueryProcessor

        # infra_db_query за feature-флагом (default-OFF, Wave 13/Q13).
        monkeypatch.setattr(feature_flags, "infra_db_query_enabled", True)
        p = InfraDbQueryProcessor(sql="SELECT 1", to="body.result")
        ex = MagicMock()
        body = {}
        ex.in_message.body = body
        ex.set_property = MagicMock()
        ctx = MagicMock()
        # Mock session manager (DatabaseSessionManager.create_session)
        session = MagicMock()
        session.execute = AsyncMock(return_value=[{"?column?": 1}])
        sm = MagicMock()
        sm.create_session = MagicMock()
        sm.create_session.return_value.__aenter__ = AsyncMock(return_value=session)
        sm.create_session.return_value.__aexit__ = AsyncMock(return_value=None)
        get_sm = MagicMock(return_value=sm)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_main_session_manager_getter",
            return_value=get_sm,
        ):
            await p.process(ex, ctx)
        assert body.get("result") == [{"?column?": 1}]


class TestDSLProcessorErrorPropagation:
    """Verify DSL processors propagate errors from underlying infra."""

    @pytest.mark.asyncio
    async def test_infra_s3_propagates_storage_error(self) -> None:
        """Ошибка backend'а пробрасывается как ServiceError (фасад оборачивает)."""
        from src.backend.core.errors import ServiceError
        from src.backend.dsl.engine.processors.infra_s3 import InfraS3GetProcessor
        from src.backend.services.storage.facade import StorageFacade

        p = InfraS3GetProcessor(key="missing.json", to="body.content")
        ex = MagicMock()
        ex.in_message.body = {}
        ctx = MagicMock()
        storage_instance = MagicMock()
        storage_instance.download = AsyncMock(side_effect=ConnectionError("S3 down"))
        facade = StorageFacade(storage=storage_instance, plugin="route-1")
        with patch(
            "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
            return_value=facade,
        ):
            with pytest.raises(ServiceError):
                await p.process(ex, ctx)

    @pytest.mark.asyncio
    async def test_infra_redis_propagates_client_error(self) -> None:
        from src.backend.dsl.engine.processors.infra_redis import InfraRedisGetProcessor

        p = InfraRedisGetProcessor(key="missing", to="body.value")
        ex = MagicMock()
        ex.in_message.body = {}
        ctx = MagicMock()
        client_instance = MagicMock()
        client_instance.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        client_class = MagicMock(return_value=client_instance)
        with patch(
            "src.backend.core.di.providers.infrastructure_locator.get_redis_client_class",
            return_value=client_class,
        ):
            with pytest.raises(ConnectionError):
                await p.process(ex, ctx)
