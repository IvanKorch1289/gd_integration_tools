"""Unit-тесты L3 retrieval-graph cache (S5 W1).

Покрывают:
1. default-OFF поведение (lookup → None, store → no-op).
2. enabled lookup/store roundtrip с TTL.
3. TTL-expiry leniency.
4. Selective invalidation по namespace.
5. publish_invalidate fallback при недоступности Redis.
"""

from __future__ import annotations

import time
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = pytest.mark.skip(reason="S171 M11 R3/R4: defer — pre-existing test pollution")

from src.backend.services.ai.semantic_cache import (
    RAG_CACHE_INVALIDATE_CHANNEL,
    L3RetrievalGraphCache,
)


def _enable_flag(monkeypatch: pytest.MonkeyPatch, value: bool = True) -> None:
    """Подменяет feature_flags.rag_cache_l3_retrieval_invalidation."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(
        feature_flags, "rag_cache_l3_retrieval_invalidation", value, raising=False
    )


@pytest.mark.asyncio
async def test_l3_lookup_returns_none_when_disabled() -> None:
    """При выключенном flag lookup всегда None и store не записывает."""
    cache = L3RetrievalGraphCache()
    await cache.store("q1", namespace="ns1", result=[{"id": "1"}])
    assert await cache.lookup("q1", namespace="ns1") is None
    assert cache._store == {}


@pytest.mark.asyncio
async def test_l3_store_and_lookup_roundtrip(monkeypatch: pytest.MonkeyPatch) -> None:
    """При enabled flag store+lookup возвращает сохранённые документы."""
    _enable_flag(monkeypatch)
    cache = L3RetrievalGraphCache()
    docs = [{"id": "d1", "score": 0.9}, {"id": "d2", "score": 0.8}]
    await cache.store("hello", namespace="ns-a", result=docs)
    hit = await cache.lookup("hello", namespace="ns-a")
    assert hit == docs
    # Разные namespace дают разные ключи
    assert await cache.lookup("hello", namespace="ns-b") is None


@pytest.mark.asyncio
async def test_l3_ttl_expiry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Запись с истёкшим TTL удаляется при lookup."""
    _enable_flag(monkeypatch)
    cache = L3RetrievalGraphCache(ttl_seconds=10)
    await cache.store("q", namespace="ns", result=[{"id": "x"}])
    # Симулируем истечение TTL переписав stored_at
    key = next(iter(cache._store))
    cache._store[key]["stored_at"] = time.time() - 100
    assert await cache.lookup("q", namespace="ns") is None
    assert cache._store == {}


@pytest.mark.asyncio
async def test_l3_invalidate_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    """invalidate_namespace удаляет только записи указанного namespace."""
    _enable_flag(monkeypatch)
    cache = L3RetrievalGraphCache()
    await cache.store("q1", namespace="ns-keep", result=[{"id": "1"}])
    await cache.store("q2", namespace="ns-drop", result=[{"id": "2"}])
    removed = cache.invalidate_namespace("ns-drop")
    assert removed == 1
    assert await cache.lookup("q1", namespace="ns-keep") is not None
    assert await cache.lookup("q2", namespace="ns-drop") is None
    # Wildcard сбрасывает всё
    removed_all = cache.invalidate_namespace("*")
    assert removed_all == 1
    assert cache._store == {}


@pytest.mark.asyncio
async def test_l3_publish_invalidate_returns_false_without_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При недоступности Redis publish_invalidate возвращает False, не падая."""
    _enable_flag(monkeypatch)
    cache = L3RetrievalGraphCache()

    def _raise(*_a: Any, **_kw: Any) -> Any:
        raise RuntimeError("redis unavailable")

    with patch(
        "src.backend.core.di.providers.get_redis_stream_client_provider",
        side_effect=_raise,
    ):
        ok = await cache.publish_invalidate("ns-x", doc_id="doc-1")
        assert ok is False


@pytest.mark.asyncio
async def test_l3_publish_invalidate_calls_redis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """publish_invalidate публикует payload в RAG_CACHE_INVALIDATE_CHANNEL."""
    _enable_flag(monkeypatch)
    cache = L3RetrievalGraphCache()

    class _FakeRaw:
        def __init__(self) -> None:
            self.calls: list[tuple[str, bytes]] = []
            self._raw_client = None  # fallback на self (lazy init raw_client)

        async def publish(self, channel: str, payload: bytes) -> int:
            self.calls.append((channel, payload))
            return 1

    fake_raw = _FakeRaw()

    from src.backend.core.di import providers as _providers

    monkeypatch.setattr(
        _providers, "get_redis_stream_client_provider", lambda: fake_raw, raising=False
    )
    ok = await cache.publish_invalidate("ns-1", doc_id="doc-42")
    assert ok is True
    assert len(fake_raw.calls) == 1
    channel, _payload = fake_raw.calls[0]
    assert channel == RAG_CACHE_INVALIDATE_CHANNEL
