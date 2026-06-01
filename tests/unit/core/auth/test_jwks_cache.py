"""Unit-тесты :class:`JwksCache`.

Покрытие:
* первый запрос → fetch + cache;
* повторный в окне TTL → cached без fetch;
* истёкший TTL → refetch;
* concurrent get_keys на холодном кеше → ровно один fetch (lock);
* network-failure при наличии cached → stale-fallback;
* network-failure при пустом кеше → JwksFetchError;
* get_key по kid возвращает корректный JWK.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from src.backend.core.auth.jwks_cache import JwksCache, JwksFetchError


class CountingFetcher:
    def __init__(self, payload: dict, *, fail: bool = False, delay: float = 0.0) -> None:
        self.payload = payload
        self.calls = 0
        self.fail = fail
        self.delay = delay

    async def fetch(self, url: str) -> dict:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise RuntimeError("network down")
        return self.payload


JWKS_PAYLOAD = {"keys": [{"kid": "k1", "kty": "RSA"}, {"kid": "k2", "kty": "EC"}]}


@pytest.mark.asyncio
async def test_first_call_triggers_fetch() -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD)
    cache = JwksCache("https://idp/jwks", ttl=10, fetcher=fetcher)
    keys = await cache.get_keys()
    assert keys == JWKS_PAYLOAD
    assert fetcher.calls == 1


@pytest.mark.asyncio
async def test_second_call_uses_cache() -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD)
    cache = JwksCache("https://idp/jwks", ttl=60, fetcher=fetcher)
    await cache.get_keys()
    await cache.get_keys()
    assert fetcher.calls == 1


@pytest.mark.asyncio
async def test_expired_ttl_refetches(monkeypatch: pytest.MonkeyPatch) -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD)
    cache = JwksCache("https://idp/jwks", ttl=10, fetcher=fetcher)
    await cache.get_keys()

    # Сдвигаем monotonic вперёд на 100 секунд — TTL должен истечь.
    real_monotonic = time.monotonic
    offset = 100.0
    monkeypatch.setattr(
        "src.backend.core.auth.jwks_cache.time.monotonic",
        lambda: real_monotonic() + offset,
    )
    await cache.get_keys()
    assert fetcher.calls == 2


@pytest.mark.asyncio
async def test_concurrent_cold_fetch_locked() -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD, delay=0.05)
    cache = JwksCache("https://idp/jwks", ttl=60, fetcher=fetcher)
    results = await asyncio.gather(*[cache.get_keys() for _ in range(10)])
    # Все запросы получают одинаковый payload, но fetcher вызван ровно раз.
    assert fetcher.calls == 1
    assert all(r == JWKS_PAYLOAD for r in results)


@pytest.mark.asyncio
async def test_network_failure_returns_stale_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD)
    cache = JwksCache("https://idp/jwks", ttl=10, fetcher=fetcher)
    await cache.get_keys()

    # Сдвигаем время за TTL.
    real_monotonic = time.monotonic
    monkeypatch.setattr(
        "src.backend.core.auth.jwks_cache.time.monotonic",
        lambda: real_monotonic() + 100,
    )
    # Симулируем падение сети — stale-fallback должен сработать.
    fetcher.fail = True
    keys = await cache.get_keys()
    assert keys == JWKS_PAYLOAD


@pytest.mark.asyncio
async def test_network_failure_without_cache_raises() -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD, fail=True)
    cache = JwksCache("https://idp/jwks", ttl=10, fetcher=fetcher)
    with pytest.raises(JwksFetchError):
        await cache.get_keys()


@pytest.mark.asyncio
async def test_get_key_returns_matching_jwk() -> None:
    fetcher = CountingFetcher(JWKS_PAYLOAD)
    cache = JwksCache("https://idp/jwks", ttl=60, fetcher=fetcher)
    key = await cache.get_key("k2")
    assert key is not None
    assert key["kty"] == "EC"

    missing = await cache.get_key("unknown")
    assert missing is None
