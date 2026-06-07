"""Sprint 21 W7 — BrowserCookieStore tests (G-06 closure).

Покрытие:
    * save → restore round-trip с TTL.
    * restart simulation: pre-saved cookies доступны после "перезапуска" store.
    * clear() удаляет ключ.
    * Multi-tenant изоляция (tenant A не видит cookies tenant B).
    * Malformed JSON — graceful fallback.
"""

from __future__ import annotations

import pytest

from src.backend.services.rpa.browser_cookies_store import BrowserCookieStore

pytestmark = pytest.mark.asyncio


class _FakeRedis:
    """In-memory mock with TTL trace для assertions."""

    def __init__(self) -> None:
        self._store: dict[str, str] = {}
        self._ttls: dict[str, int] = {}

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._store[key] = value
        if ex is not None:
            self._ttls[key] = ex

    async def get(self, key: str) -> str | None:
        return self._store.get(key)

    async def delete(self, *keys: str) -> int:
        deleted = 0
        for k in keys:
            if k in self._store:
                del self._store[k]
                deleted += 1
        return deleted


@pytest.fixture
def store() -> tuple[BrowserCookieStore, _FakeRedis]:
    redis = _FakeRedis()
    return BrowserCookieStore(redis), redis


async def test_save_and_restore_round_trip(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    s, _redis = store
    cookies = [
        {"name": "session_id", "value": "abc123", "domain": "example.com"},
        {"name": "csrf", "value": "xyz", "domain": "example.com"},
    ]
    await s.save_cookies(
        tenant_id="bank_a", user_id="u42", domain="example.com", cookies=cookies
    )
    restored = await s.restore_cookies(
        tenant_id="bank_a", user_id="u42", domain="example.com"
    )
    assert restored == cookies


async def test_restore_empty_when_no_session(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    s, _ = store
    result = await s.restore_cookies(
        tenant_id="bank_a", user_id="u42", domain="example.com"
    )
    assert result == []


async def test_worker_restart_simulation() -> None:
    """G-06 acceptance — cookies survive симуляцию worker restart."""
    # Worker 1: save cookies
    redis = _FakeRedis()
    s1 = BrowserCookieStore(redis)
    await s1.save_cookies(
        tenant_id="t",
        user_id="u",
        domain="d.com",
        cookies=[{"name": "auth", "value": "tok"}],
    )

    # Worker 2: новый instance Store с тем же redis backend
    s2 = BrowserCookieStore(redis)
    restored = await s2.restore_cookies(tenant_id="t", user_id="u", domain="d.com")
    assert restored == [{"name": "auth", "value": "tok"}]


async def test_multi_tenant_isolation(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    """Tenant A не видит cookies tenant B."""
    s, _ = store
    await s.save_cookies(
        tenant_id="bank_a", user_id="u", domain="d.com", cookies=[{"name": "tok_a"}]
    )
    await s.save_cookies(
        tenant_id="bank_b", user_id="u", domain="d.com", cookies=[{"name": "tok_b"}]
    )
    a = await s.restore_cookies(tenant_id="bank_a", user_id="u", domain="d.com")
    b = await s.restore_cookies(tenant_id="bank_b", user_id="u", domain="d.com")
    assert a == [{"name": "tok_a"}]
    assert b == [{"name": "tok_b"}]


async def test_clear_deletes_session(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    s, _ = store
    await s.save_cookies(
        tenant_id="t", user_id="u", domain="d.com", cookies=[{"name": "x"}]
    )
    await s.clear(tenant_id="t", user_id="u", domain="d.com")
    restored = await s.restore_cookies(tenant_id="t", user_id="u", domain="d.com")
    assert restored == []


async def test_ttl_passed_to_redis(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    s, redis = store
    await s.save_cookies(
        tenant_id="t", user_id="u", domain="d.com", cookies=[{"name": "x"}]
    )
    key = next(iter(redis._store))
    assert redis._ttls[key] == 86400  # 24h default


async def test_empty_cookies_skipped(
    store: tuple[BrowserCookieStore, _FakeRedis],
) -> None:
    """Empty cookies — no-op (не пишем ничего)."""
    s, redis = store
    await s.save_cookies(tenant_id="t", user_id="u", domain="d.com", cookies=[])
    assert redis._store == {}


async def test_malformed_json_returns_empty() -> None:
    """Malformed JSON в Redis — graceful fallback."""

    class _BadRedis:
        async def set(self, key: str, value: str, ex: int | None = None) -> None:
            pass

        async def get(self, key: str) -> str:
            return "not json {{"

        async def delete(self, *keys: str) -> int:
            return 0

    s = BrowserCookieStore(_BadRedis())
    restored = await s.restore_cookies(tenant_id="t", user_id="u", domain="d.com")
    assert restored == []


async def test_invalid_ttl_raises() -> None:
    redis = _FakeRedis()
    with pytest.raises(ValueError):
        BrowserCookieStore(redis, ttl_seconds=0)
