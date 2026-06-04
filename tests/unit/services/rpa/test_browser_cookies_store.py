"""Unit tests for src.backend.services.rpa.browser_cookies_store."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.backend.services.rpa.browser_cookies_store import BrowserCookieStore


def _fake_redis() -> AsyncMock:
    redis = AsyncMock()
    redis.set = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.delete = AsyncMock(return_value=1)
    return redis


class TestInit:
    def test_bad_ttl(self) -> None:
        with pytest.raises(ValueError, match="ttl_seconds"):
            BrowserCookieStore(_fake_redis(), ttl_seconds=0)


class TestMakeKey:
    def test_normal(self) -> None:
        store = BrowserCookieStore(_fake_redis())
        assert (
            store._make_key("t1", "u1", "example.com")
            == "browser:session:t1:u1:example.com"
        )

    def test_empty_parts(self) -> None:
        store = BrowserCookieStore(_fake_redis())
        assert store._make_key("", "", "") == "browser:session:_:_:_"


class TestSaveAndRestore:
    async def test_roundtrip(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis)
        cookies = [{"name": "sid", "value": "abc"}]
        await store.save_cookies(
            tenant_id="t1", user_id="u1", domain="d1", cookies=cookies
        )
        redis.set.assert_awaited_once()

        redis.get = AsyncMock(return_value='[{"name": "sid", "value": "abc"}]')
        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == cookies

    async def test_save_empty(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis)
        await store.save_cookies(tenant_id="t1", user_id="u1", domain="d1", cookies=[])
        redis.set.assert_not_awaited()

    async def test_restore_missing(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis)
        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == []

    async def test_restore_bytes(self) -> None:
        redis = _fake_redis()
        redis.get = AsyncMock(return_value=b'[{"x": 1}]')
        store = BrowserCookieStore(redis)
        result = await store.restore_cookies(tenant_id="t1", user_id="u1", domain="d1")
        assert result == [{"x": 1}]

    async def test_restore_malformed(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.get = AsyncMock(return_value="not-json")
        store = BrowserCookieStore(redis)
        with caplog.at_level("WARNING"):
            result = await store.restore_cookies(
                tenant_id="t1", user_id="u1", domain="d1"
            )
        assert result == []
        assert "malformed" in caplog.text

    async def test_restore_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.get = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis)
        with caplog.at_level("WARNING"):
            result = await store.restore_cookies(
                tenant_id="t1", user_id="u1", domain="d1"
            )
        assert result == []
        assert "failed" in caplog.text

    async def test_save_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.set = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis)
        with caplog.at_level("WARNING"):
            await store.save_cookies(
                tenant_id="t1", user_id="u1", domain="d1", cookies=[{"x": 1}]
            )
        assert "failed" in caplog.text

    async def test_clear(self) -> None:
        redis = _fake_redis()
        store = BrowserCookieStore(redis)
        await store.clear(tenant_id="t1", user_id="u1", domain="d1")
        redis.delete.assert_awaited_once()

    async def test_clear_exception(self, caplog: pytest.LogCaptureFixture) -> None:
        redis = _fake_redis()
        redis.delete = AsyncMock(side_effect=ConnectionError("down"))
        store = BrowserCookieStore(redis)
        with caplog.at_level("WARNING"):
            await store.clear(tenant_id="t1", user_id="u1", domain="d1")
        assert "failed" in caplog.text
