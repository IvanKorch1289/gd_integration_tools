"""S90 W4 — Pool registration regression tests (MongoDB + Elasticsearch).

V3 #5: verify _register_pools_in_unified_manager registers the
new MongoDB and Elasticsearch pools when their respective
enabled flags are set.

Note: get_unified_pool_manager is imported lazily inside the function
(try/except ImportError), so we patch it on the source module.
The accessor is treated as a singleton; tests use a module-level
container to preserve registrations across calls.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest


class _FakeManager:
    """Minimal stand-in for UnifiedPoolManager (singleton)."""

    def __init__(self) -> None:
        self.pools: dict[str, dict[str, Any]] = {}

    def register(self, name: str, pool: Any, ping_fn: Any, kind: str, **_: Any) -> None:
        self.pools[name] = {"pool": pool, "ping_fn": ping_fn, "kind": kind}

    def list_pools(self) -> list[str]:
        return list(self.pools.keys())


@pytest.fixture
def fake_manager(monkeypatch: Any) -> _FakeManager:
    """Singleton fake manager wired into the lazy-imported accessor."""
    manager = _FakeManager()
    import src.backend.infrastructure.clients.unified_pool_manager as upm

    monkeypatch.setattr(upm, "get_unified_pool_manager", lambda: manager)
    return manager


@pytest.fixture
def stub_optional_dependencies(monkeypatch: Any) -> None:
    """Disable db/redis/s3/clickhouse branches in the registration function."""
    from src.backend.plugins.composition.setup_infra import pools

    monkeypatch.setattr(pools, "_redis_enabled", lambda: False)
    monkeypatch.setattr(pools, "_s3_enabled", lambda: False)
    monkeypatch.setattr(pools, "_clickhouse_enabled", lambda: False)
    monkeypatch.setattr(
        pools,
        "get_db_initializer",
        lambda: (_ for _ in ()).throw(Exception("db not available")),
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_mongo_pool_registered_when_enabled(
    fake_manager: _FakeManager, stub_optional_dependencies: None, monkeypatch: Any
) -> None:
    """MongoDB pool registers when settings.mongo.enabled=True."""
    from src.backend.plugins.composition.setup_infra import pools

    fake_mongo = MagicMock()
    fake_mongo.ping = MagicMock(return_value=True)
    monkeypatch.setattr(pools, "get_mongo_client", lambda: fake_mongo)
    monkeypatch.setattr(pools, "_mongo_enabled", lambda: True)
    monkeypatch.setattr(pools, "_es_enabled", lambda: False)

    await pools._register_pools_in_unified_manager()

    assert "mongodb_main" in fake_manager.pools
    assert fake_manager.pools["mongodb_main"]["kind"] == "mongodb"
    assert fake_manager.pools["mongodb_main"]["pool"] is fake_mongo


@pytest.mark.unit
@pytest.mark.asyncio
async def test_es_pool_registered_when_enabled(
    fake_manager: _FakeManager, stub_optional_dependencies: None, monkeypatch: Any
) -> None:
    """Elasticsearch pool registers when settings.elasticsearch.enabled=True."""
    from src.backend.plugins.composition.setup_infra import pools

    fake_es = MagicMock()
    fake_es.ping = MagicMock(return_value=True)
    monkeypatch.setattr(pools, "get_elasticsearch_client", lambda: fake_es)
    monkeypatch.setattr(pools, "_mongo_enabled", lambda: False)
    monkeypatch.setattr(pools, "_es_enabled", lambda: True)

    await pools._register_pools_in_unified_manager()

    assert "elasticsearch_main" in fake_manager.pools
    assert fake_manager.pools["elasticsearch_main"]["kind"] == "elasticsearch"
    assert fake_manager.pools["elasticsearch_main"]["pool"] is fake_es


@pytest.mark.unit
@pytest.mark.asyncio
async def test_pools_skipped_when_disabled(
    fake_manager: _FakeManager, stub_optional_dependencies: None, monkeypatch: Any
) -> None:
    """MongoDB and ES pools do NOT register when their enabled flags are False."""
    from src.backend.plugins.composition.setup_infra import pools

    monkeypatch.setattr(pools, "_mongo_enabled", lambda: False)
    monkeypatch.setattr(pools, "_es_enabled", lambda: False)

    await pools._register_pools_in_unified_manager()

    assert "mongodb_main" not in fake_manager.pools
    assert "elasticsearch_main" not in fake_manager.pools
