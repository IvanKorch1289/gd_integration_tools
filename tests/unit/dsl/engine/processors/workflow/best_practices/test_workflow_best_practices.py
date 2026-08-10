"""TDD: WorkflowContinueAsNewProcessor + WorkflowClaimCheckProcessor."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _allow_workflow_capability(monkeypatch):
    """P3 S172 W2 — workflow best_practices требует capability (default-deny).

    Backward-compatible: existing tests patches ``check_source_capability``
    чтобы auth_check возвращал True. Реальный auth-gate покрыт тестами
    ниже (TestWorkflowCapabilityGating).
    """
    async def _allow(*args, **kwargs):
        return True

    monkeypatch.setattr(
        "src.backend.core.security.connector_auth.check_source_capability",
        _allow,
    )


class TestWorkflowContinueAsNewProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
            WorkflowContinueAsNewProcessor,
        )
        p = WorkflowContinueAsNewProcessor(
            same_workflow_id=True, same_input=True,
        )
        assert p.same_workflow_id is True

    @pytest.mark.asyncio
    async def test_continue_with_marker(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
            WorkflowContinueAsNewProcessor,
        )
        p = WorkflowContinueAsNewProcessor(same_workflow_id=True)
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"step": 50}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        ex.set_property.assert_called_once()
        args, _ = ex.set_property.call_args
        assert "continue_as_new_requested" in args[0]


class TestWorkflowClaimCheckProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )
        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=100,
            storage_backend="s3",
            bucket="payloads",
        )
        assert p.storage_backend == "s3"
        assert p.bucket == "payloads"

    @pytest.mark.asyncio
    async def test_store_oversized_payload(self, monkeypatch) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        # S210: mock S3 client — старая версия теста была рассчитана на
        # scaffold-only no-op. Теперь backend реальный → нужен mock.
        put_calls: list[dict] = {}

        class _FakeS3Client:
            async def put_object(self, key, body, metadata):
                put_calls["key"] = key
                put_calls["body"] = body
                return {"status": "success"}

        def _fake_get_s3_client(*args, **kwargs):
            return _FakeS3Client()

        import types

        fake_module = types.ModuleType(
            "src.backend.infrastructure.clients.storage.s3_pool",
        )
        fake_module.get_s3_client = _fake_get_s3_client
        import sys

        monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)

        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=100,
            storage_backend="s3",
            bucket="payloads",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"payload": {"large": "x" * 1000}}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert ex.in_message.body.get("payload_claim") is not None
        assert put_calls["key"].startswith("payloads/")
        assert len(put_calls["body"]) > 100


class TestWorkflowClaimCheckRedisBackend:
    """Redis backend: реальный store через redis_client.cache_set."""

    @staticmethod
    def _install_redis_fake(monkeypatch, fake_client):
        """Install fake redis module via types.ModuleType."""
        import sys
        import types

        fake_module = types.ModuleType(
            "src.backend.infrastructure.clients.storage.redis",
        )
        fake_module.redis_client = fake_client
        monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
        return fake_module

    @pytest.mark.asyncio
    async def test_store_calls_redis_cache_set(self, monkeypatch) -> None:
        """Oversized payload → redis_client.cache_set вызван с правильным ключом и TTL."""
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        calls: list[tuple[str, bytes, int]] = []

        class _FakeRedisClient:
            async def cache_set(self, key, value, expire):
                calls.append((key, value, expire))

            async def cache_get(self, key):
                for ck, cv, _ in calls:
                    if ck == key:
                        return cv
                return None

        self._install_redis_fake(monkeypatch, _FakeRedisClient())

        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=10,
            storage_backend="redis",
            bucket="test-claims",
            ttl_seconds=120,
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"payload": {"data": "x" * 100}}
        await p.process(ex, MagicMock())

        assert len(calls) == 1
        key, value, expire = calls[0]
        assert key.startswith("test-claims/")
        assert expire == 120
        assert len(value) > 10

    @pytest.mark.asyncio
    async def test_load_from_redis(self, monkeypatch) -> None:
        """load_payload возвращает данные ранее сохранённые в redis."""
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        store: dict[str, bytes] = {}

        class _FakeRedisClient:
            async def cache_set(self, key, value, expire):
                store[key] = value

            async def cache_get(self, key):
                return store.get(key)

        self._install_redis_fake(monkeypatch, _FakeRedisClient())

        p = WorkflowClaimCheckProcessor(
            storage_backend="redis",
            ttl_seconds=300,
        )
        await p._store_redis("k1", b"payload-bytes")
        loaded = await p.load_payload("k1")
        assert loaded == b"payload-bytes"

    @pytest.mark.asyncio
    async def test_load_missing_redis_returns_none(self, monkeypatch) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        class _FakeRedisClient:
            async def cache_get(self, key):
                return None

        self._install_redis_fake(monkeypatch, _FakeRedisClient())

        p = WorkflowClaimCheckProcessor(storage_backend="redis")
        assert await p.load_payload("nonexistent") is None


class TestWorkflowClaimCheckS3Backend:
    """S3 backend: реальный store через s3.put_object."""

    @staticmethod
    def _install_s3_fake(monkeypatch, fake_client_factory):
        """Install fake s3_pool module via types.ModuleType."""
        import sys
        import types

        def _factory(*args, **kwargs):
            return fake_client_factory()

        fake_module = types.ModuleType(
            "src.backend.infrastructure.clients.storage.s3_pool",
        )
        fake_module.get_s3_client = _factory
        monkeypatch.setitem(sys.modules, fake_module.__name__, fake_module)
        return fake_module

    @pytest.mark.asyncio
    async def test_store_calls_s3_put_object(self, monkeypatch) -> None:
        """Oversized payload → s3.put_object вызван с правильным ключом."""
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        put_calls: list[dict] = {}

        class _FakeS3Client:
            async def put_object(self, key, body, metadata):
                put_calls["key"] = key
                put_calls["body"] = body
                put_calls["metadata"] = metadata
                return {"status": "success"}

            async def get_object_bytes(self, key):
                if put_calls.get("key") == key:
                    return put_calls["body"]
                return None

        self._install_s3_fake(monkeypatch, _FakeS3Client)

        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=10,
            storage_backend="s3",
            bucket="my-bucket",
            ttl_seconds=600,
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"payload": {"big": "y" * 200}}
        await p.process(ex, MagicMock())

        assert put_calls["key"].startswith("my-bucket/")
        assert len(put_calls["body"]) > 10
        assert put_calls["metadata"]["ttl_seconds"] == "600"

    @pytest.mark.asyncio
    async def test_load_from_s3(self, monkeypatch) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        store: dict[str, bytes] = {}

        class _FakeS3Client:
            async def put_object(self, key, body, metadata):
                store[key] = body
                return {"status": "success"}

            async def get_object_bytes(self, key):
                return store.get(key)

        self._install_s3_fake(monkeypatch, _FakeS3Client)

        p = WorkflowClaimCheckProcessor(storage_backend="s3")
        await p._store_s3("obj1", b"s3-bytes")
        assert await p.load_payload("obj1") == b"s3-bytes"

    @pytest.mark.asyncio
    async def test_load_missing_s3_returns_none(self, monkeypatch) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        class _FakeS3Client:
            async def get_object_bytes(self, key):
                return None

        self._install_s3_fake(monkeypatch, _FakeS3Client)

        p = WorkflowClaimCheckProcessor(storage_backend="s3")
        assert await p.load_payload("ghost") is None


class TestWorkflowCapabilityGating:
    """P3 S172 W2: capability-gate для workflow best_practices."""

    def test_workflow_claim_check_class_declares_required_capability(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )
        assert (
            WorkflowClaimCheckProcessor.required_capability
            == "workflow.claim_check.store"
        )
        assert (
            WorkflowClaimCheckProcessor.audit_event == "workflow.claim_check.stored"
        )

    def test_workflow_continue_as_new_class_declares_required_capability(self) -> None:
        from src.backend.dsl.engine.processors.workflow.best_practices.continue_as_new import (
            WorkflowContinueAsNewProcessor,
        )
        assert (
            WorkflowContinueAsNewProcessor.required_capability
            == "workflow.continue_as_new.request"
        )
        assert (
            WorkflowContinueAsNewProcessor.audit_event
            == "workflow.continue_as_new.requested"
        )

    @pytest.mark.asyncio
    async def test_workflow_claim_check_auth_denied_skips_storage(
        self, monkeypatch,
    ) -> None:
        """Denied capability → process() возвращается без payload token."""
        async def _deny(*args, **kwargs):
            return False

        monkeypatch.setattr(
            "src.backend.core.security.connector_auth.check_source_capability",
            _deny,
        )

        from src.backend.dsl.engine.processors.workflow.best_practices.claim_check import (
            WorkflowClaimCheckProcessor,
        )

        p = WorkflowClaimCheckProcessor(
            source_property="body.payload",
            max_size_bytes=10,
            storage_backend="s3",
            bucket="payloads",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {"payload": {"large": "x" * 1000}}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        # Body не модифицирован.
        assert ex.in_message.body.get("payload_claim") is None
        ex.set_error.assert_called_once()
