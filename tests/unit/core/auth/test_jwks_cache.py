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

from src.backend.core.auth.jwks_cache import (
    JwksCache,
    JwksConfigurationError,
    JwksFetchError,
)


class CountingFetcher:
    def __init__(
        self, payload: dict, *, fail: bool = False, delay: float = 0.0
    ) -> None:
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

#: Оригинальный ``time.monotonic`` — чтобы сдвиги в тестах были абсолютными.
_REAL_MONOTONIC = time.monotonic


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


# ── ADR-0419: предельное окно stale-fallback + HTTPS-only/SSRF ──────


class TestJwksUrlHardening:
    """ADR-0419: ``jwks_url`` — только https + SSRF-guard."""

    def test_http_url_is_configuration_error(self) -> None:
        """http:// — ошибка конфигурации, а не молчаливый downgrade."""
        with pytest.raises(JwksConfigurationError) as exc_info:
            JwksCache("http://idp/jwks")
        assert "https" in str(exc_info.value)

    def test_non_http_scheme_is_rejected(self) -> None:
        """Не-HTTP схема отвергается."""
        with pytest.raises(JwksConfigurationError):
            JwksCache("ftp://idp/jwks")

    def test_empty_url_is_rejected(self) -> None:
        """Пустой URL — ошибка конфигурации."""
        with pytest.raises(JwksConfigurationError):
            JwksCache("   ")

    def test_metadata_host_is_rejected(self) -> None:
        """SSRF-guard: хост metadata-endpoint'а отвергается."""
        with pytest.raises(JwksConfigurationError):
            JwksCache("https://metadata.google.internal/.well-known/jwks.json")

    def test_https_url_is_accepted(self) -> None:
        """Корректный https-URL принимается."""
        cache = JwksCache("https://auth.example.com/.well-known/jwks.json")
        assert cache.url == "https://auth.example.com/.well-known/jwks.json"


class TestStaleWindow:
    """ADR-0419: stale-кеш JWKS живёт не дольше предельного окна."""

    @staticmethod
    def _shift(monkeypatch: pytest.MonkeyPatch, seconds: float) -> None:
        """Сдвинуть monotonic на ``seconds`` (абсолютно от реального now)."""
        monkeypatch.setattr(
            "src.backend.core.auth.jwks_cache.time.monotonic",
            lambda: _REAL_MONOTONIC() + seconds,
        )

    @pytest.mark.asyncio
    async def test_stale_used_inside_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """В окне stale-fallback старый JWKS ещё отдаётся."""
        fetcher = CountingFetcher(JWKS_PAYLOAD)
        cache = JwksCache(
            "https://idp/jwks", ttl=10, fetcher=fetcher, max_stale_seconds=60
        )
        await cache.get_keys()

        self._shift(monkeypatch, 40)  # TTL (10) истёк, окно stale (до 70) — нет
        fetcher.fail = True
        assert await cache.get_keys() == JWKS_PAYLOAD

    @pytest.mark.asyncio
    async def test_stale_rejected_after_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """За предельным окном stale-fallback отключён (fail-closed)."""
        fetcher = CountingFetcher(JWKS_PAYLOAD)
        cache = JwksCache(
            "https://idp/jwks", ttl=10, fetcher=fetcher, max_stale_seconds=60
        )
        await cache.get_keys()

        self._shift(monkeypatch, 71)  # TTL (10) + окно stale (60) истекли
        fetcher.fail = True
        with pytest.raises(JwksFetchError):
            await cache.get_keys()

    @pytest.mark.asyncio
    async def test_zero_max_stale_disables_fallback(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``max_stale_seconds=0`` — stale-fallback полностью выключен."""
        fetcher = CountingFetcher(JWKS_PAYLOAD)
        cache = JwksCache(
            "https://idp/jwks", ttl=10, fetcher=fetcher, max_stale_seconds=0
        )
        await cache.get_keys()

        self._shift(monkeypatch, 11)
        fetcher.fail = True
        with pytest.raises(JwksFetchError):
            await cache.get_keys()

    @pytest.mark.asyncio
    async def test_successful_refresh_resets_stale_window(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Успешный refresh продлевает окно stale заново."""
        fetcher = CountingFetcher(JWKS_PAYLOAD)
        cache = JwksCache(
            "https://idp/jwks", ttl=10, fetcher=fetcher, max_stale_seconds=60
        )
        await cache.get_keys()

        self._shift(monkeypatch, 11)  # TTL истёк → refresh
        await cache.get_keys()
        assert fetcher.calls == 2

        # Окно stale отсчитывается от последнего успешного refresh.
        self._shift(monkeypatch, 11 + 40)
        fetcher.fail = True
        assert await cache.get_keys() == JWKS_PAYLOAD
