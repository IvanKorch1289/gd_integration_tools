"""Unit tests for src.backend.services.rpa.browser_cookies_store."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

# Cycle 33 RPA1: explicit Fernet key for test isolation.
from cryptography.fernet import Fernet

from src.backend.services.rpa.browser_cookies_store import BrowserCookieStore

_TEST_FERNET_KEY = Fernet.generate_key()


def _fake_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


class TestInit:
    def test_bad_ttl(self) -> None:
        with pytest.raises(ValueError, match="ttl_seconds"):
            BrowserCookieStore(
                _fake_redis(), ttl_seconds=0, fernet_key=_TEST_FERNET_KEY
            )

    def test_invalid_fernet_key_raises(self) -> None:
        """Constructor rejects non-44-byte Fernet key."""
        with pytest.raises(ValueError, match="Fernet key"):
            BrowserCookieStore(_fake_redis(), fernet_key=b"too-short")


class TestMakeKey:
    def test_normal(self) -> None:
        store = BrowserCookieStore(_fake_redis(), fernet_key=_TEST_FERNET_KEY)
        assert (
            store._make_key("t1", "u1", "example.com")
            == "browser:session:t1:u1:example.com"
        )

    def test_empty_parts(self) -> None:
        store = BrowserCookieStore(_fake_redis(), fernet_key=_TEST_FERNET_KEY)
        assert store._make_key("", "", "") == "browser:session:_:_:_"


class TestSaveAndRestore:
    async def test_roundtrip(self) -> None:
        # Cycle 33 RPA1: cookies are Fernet-encrypted before save. Build
        # a redis mock that stores the encrypted value and returns it on get.
        from cryptography.fernet import Fernet

        Fernet(_TEST_FERNET_KEY)  # verify key is valid
        stored: dict[str, bytes] = {}

        async def _set(key: str, value: bytes, ex: int | None = None) -> None:
            stored[key] = value

        async def _get(key: str) -> bytes | None:
            return stored.get(key)

        redis = AsyncMock()
        redis.set = AsyncMock(side_effect=_set)
        redis.get = AsyncMock(side_effect=_get)
        redis.delete = AsyncMock(return_value=1)

        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        cookies = [{"name": "sid", "value": "abc"}]
        await store.save_cookies(
            tenant_id="t1", user_id="u1", domain="d1", cookies=cookies
        )
        # Verify the stored value is encrypted (not plaintext JSON).
        assert len(stored) == 1
        raw = next(iter(stored.values()))
        assert b'"sid"' not in raw  # Fernet ciphertext doesn't contain plaintext
        assert b'"abc"' not in raw

        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == cookies
        assert result == cookies

    async def test_save_empty(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        await store.save_cookies(tenant_id="t1", user_id="u1", domain="d1", cookies=[])
        redis.set.assert_not_awaited()

    async def test_restore_missing(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == []

    async def test_restore_bytes(self) -> None:
        """Cycle 33 RPA1: restore returns decrypted cookies correctly.

        Note: prior plaintext behavior is no longer supported — restore
        always Fernet-decrypts. This test verifies the happy path.
        """
        redis = _fake_redis()
        fernet = Fernet(_TEST_FERNET_KEY)
        encrypted = fernet.encrypt(b'[{"x": 1}]')
        redis.get = AsyncMock(return_value=encrypted)
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == [{"x": 1}]

    async def test_restore_malformed(self, caplog: pytest.LogCaptureFixture) -> None:
        """Malformed bytes (not valid Fernet token) → decrypt fails gracefully."""
        redis = _fake_redis()
        redis.get = AsyncMock(return_value=b"not-valid-fernet-token")
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        with caplog.at_level("WARNING"):
            result = await store.restore_cookies(
                tenant_id="t1", user_id="u1", domain="d1"
            )
        assert result == []
        assert "decrypt failed" in caplog.text

    async def test_restore_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.get = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        with caplog.at_level("WARNING"):
            result = await store.restore_cookies(
                tenant_id="t1", user_id="u1", domain="d1"
            )
        assert result == []
        assert "failed" in caplog.text

    async def test_save_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.set = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        with caplog.at_level("WARNING"):
            await store.save_cookies(
                tenant_id="t1", user_id="u1", domain="d1", cookies=[{"x": 1}]
            )
        assert "failed" in caplog.text

    async def test_clear(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        await store.clear(tenant_id="t1", user_id="u1", domain="d1")
        redis.delete.assert_awaited_once()

    async def test_clear_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.delete = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        with caplog.at_level("WARNING"):
            await store.clear(tenant_id="t1", user_id="u1", domain="d1")
        assert "failed" in caplog.text

    async def test_dedup_skips_redis_set_when_unchanged(self) -> None:
        """Cycle 35: when cookies unchanged from last save, skip Redis.set.

        Saves one Redis write per navigation event in browser_pool.
        Critical for high-traffic RPA scenarios (e.g. scraping many pages).
        """
        redis = AsyncMock()
        Fernet(_TEST_FERNET_KEY)
        stored: dict[str, bytes] = {}

        async def _set(key: str, value: bytes, ex: int | None = None) -> None:
            stored[key] = value

        async def _get(key: str) -> bytes | None:
            return stored.get(key)

        redis.set = AsyncMock(side_effect=_set)
        redis.get = AsyncMock(side_effect=_get)

        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        cookies = [{"name": "sid", "value": "abc"}, {"name": "csrf", "value": "xyz"}]

        # First save: stores
        await store.save_cookies(
            tenant_id="t1", user_id="u1", domain="d1", cookies=cookies
        )
        assert len(stored) == 1
        first_write_count = redis.set.await_count

        # Same cookies, different order — dedup should still skip
        await store.save_cookies(
            tenant_id="t1", user_id="u1", domain="d1", cookies=list(reversed(cookies))
        )
        assert redis.set.await_count == first_write_count  # NO new write

        # Different cookie values — should write
        cookies[0]["value"] = "def"
        await store.save_cookies(
            tenant_id="t1", user_id="u1", domain="d1", cookies=cookies
        )
        assert redis.set.await_count == first_write_count + 1


class _InMemoryRedis:
    """Минимальный Redis-клсс: хранит значения и TTL."""

    def __init__(self) -> None:
        self._store: dict[str, bytes] = {}
        self._ttls: dict[str, int] = {}

    async def set(self, key: str, value: bytes, ex: int | None = None) -> None:
        """Сохранить значение (и TTL, если задан)."""
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex

    async def get(self, key: str) -> bytes | None:
        """Вернуть значение по ключу (None — если отсутствует)."""
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        """Удалить ключи, вернуть количество удалённых."""
        deleted = 0
        for key in keys:
            if key in self._store:
                del self._store[key]
                deleted += 1
        return deleted


class TestMultiTenantIsolation:
    """Tenant A не видит cookies tenant B (перенесено из tests/rpa/)."""

    async def test_tenant_isolation(self) -> None:
        redis = _InMemoryRedis()
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)

        await store.save_cookies(
            tenant_id="bank_a",
            user_id="u",
            domain="d.com",
            cookies=[{"name": "tok_a"}],
        )
        await store.save_cookies(
            tenant_id="bank_b",
            user_id="u",
            domain="d.com",
            cookies=[{"name": "tok_b"}],
        )

        assert await store.restore_cookies(
            tenant_id="bank_a", user_id="u", domain="d.com"
        ) == [{"name": "tok_a"}]
        assert await store.restore_cookies(
            tenant_id="bank_b", user_id="u", domain="d.com"
        ) == [{"name": "tok_b"}]


class TestTtl:
    """TTL в Redis — 24h по умолчанию (перенесено из tests/rpa/)."""

    async def test_default_ttl_passed_to_redis(self) -> None:
        redis = _InMemoryRedis()
        store = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        await store.save_cookies(
            tenant_id="t", user_id="u", domain="d.com", cookies=[{"name": "x"}]
        )
        key = next(iter(redis._store))
        assert redis._ttls[key] == 86400


class TestWorkerRestart:
    """Cookies переживают «рестарт worker'а» (перенесено из tests/rpa/)."""

    async def test_cookies_survive_new_store_instance(self) -> None:
        redis = _InMemoryRedis()
        first = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        await first.save_cookies(
            tenant_id="t",
            user_id="u",
            domain="d.com",
            cookies=[{"name": "auth", "value": "tok"}],
        )

        # Новый инстанс store на том же Redis — эмуляция рестарта worker'а.
        second = BrowserCookieStore(redis, fernet_key=_TEST_FERNET_KEY)
        restored = await second.restore_cookies(
            tenant_id="t", user_id="u", domain="d.com"
        )
        assert restored == [{"name": "auth", "value": "tok"}]

