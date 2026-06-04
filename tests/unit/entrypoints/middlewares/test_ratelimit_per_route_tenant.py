"""Unit-тесты per-route + tenant-aware extension (S18 W7).

Покрытие:
    * tenant_aware_identifier: X-Tenant-ID > X-User-ID > client.host.
    * RedisRateLimitChecker: incr+expire pattern, fail-open на Redis error.
    * GlobalRateLimitMiddleware per-route override: longest-prefix-match
      выбирает route_checker; miss → global checker.
    * Feature-flag default-OFF: middleware прозрачен без явного
      feature_enabled.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.entrypoints.middlewares.global_ratelimit import (
    FakeRateLimitChecker,
    GlobalRateLimitMiddleware,
    RedisRateLimitChecker,
    tenant_aware_identifier,
)

# ----------------------------- identifier ---------------------------------


class TestTenantAwareIdentifier:
    def test_tenant_id_priority(self) -> None:
        scope = {
            "headers": [(b"x-tenant-id", b"acme"), (b"x-user-id", b"alice")],
            "client": ("1.2.3.4", 0),
        }
        assert tenant_aware_identifier(scope) == "tenant:acme"

    def test_user_id_fallback(self) -> None:
        scope = {"headers": [(b"x-user-id", b"alice")], "client": ("1.2.3.4", 0)}
        assert tenant_aware_identifier(scope) == "user:alice"

    def test_ip_fallback(self) -> None:
        scope = {"headers": [], "client": ("1.2.3.4", 0)}
        assert tenant_aware_identifier(scope) == "ip:1.2.3.4"


# ----------------------------- RedisRateLimitChecker -----------------------


class _FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.store: dict[str, int] = {}
        self.fail = fail
        self.expire_calls: list[tuple[str, int]] = []

    async def incr(self, key: str) -> int:
        if self.fail:
            raise RuntimeError("redis down")
        self.store[key] = self.store.get(key, 0) + 1
        return self.store[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.expire_calls.append((key, ttl))


class TestRedisRateLimitChecker:
    async def test_allow_within_limit(self) -> None:
        redis = _FakeRedis()
        checker = RedisRateLimitChecker(redis, max_per_window=3, window_seconds=60.0)
        allowed, remaining, retry_after = await checker.check("user:1")
        assert allowed is True
        assert remaining == 2  # 3 - 1
        assert retry_after == 0
        assert redis.expire_calls  # TTL set on first call

    async def test_deny_when_exhausted(self) -> None:
        redis = _FakeRedis()
        checker = RedisRateLimitChecker(redis, max_per_window=2, window_seconds=60.0)
        await checker.check("user:1")
        await checker.check("user:1")
        allowed, remaining, retry_after = await checker.check("user:1")
        assert allowed is False
        assert remaining == 0
        assert retry_after == 60

    async def test_redis_failure_is_fail_open(self) -> None:
        """Защитный fallback: ошибка Redis → pass-through (не SPoF)."""
        redis = _FakeRedis(fail=True)
        checker = RedisRateLimitChecker(redis, max_per_window=2, window_seconds=60.0)
        allowed, remaining, retry_after = await checker.check("user:1")
        assert allowed is True
        assert retry_after == 0


# ----------------------------- per-route override --------------------------


class _RecordingApp:
    def __init__(self) -> None:
        self.calls: int = 0

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        self.calls += 1


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


class _CollectingSend:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, event: dict[str, Any]) -> None:
        self.events.append(event)


def _scope(path: str = "/api/healthz", **extra: Any) -> dict[str, Any]:
    return {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": [],
        "client": ("127.0.0.1", 0),
        **extra,
    }


class TestPerRouteOverride:
    """advisor pt 3 pattern: longest-prefix-match среди route_checkers."""

    async def test_route_specific_checker_used(self) -> None:
        global_ck = FakeRateLimitChecker(max_per_window=100, window_seconds=60.0)
        # heavy_ck — лимит 1 запрос/окно (быстро исчерпается).
        heavy_ck = FakeRateLimitChecker(max_per_window=1, window_seconds=60.0)
        app = _RecordingApp()
        mw = GlobalRateLimitMiddleware(
            app,
            checker=global_ck,
            feature_enabled=lambda: True,
            route_checkers={"/api/v1/heavy": heavy_ck},
        )
        # 1-й запрос на heavy: allowed (heavy_ck max=1).
        await mw(_scope("/api/v1/heavy/process"), _empty_receive, _CollectingSend())
        assert app.calls == 1
        # 2-й запрос на heavy: deny через heavy_ck (а не global_ck).
        send2 = _CollectingSend()
        await mw(_scope("/api/v1/heavy/process"), _empty_receive, send2)
        assert app.calls == 1  # second не дошёл до app
        assert send2.events[0]["status"] == 429

    async def test_global_fallback_on_path_miss(self) -> None:
        global_ck = FakeRateLimitChecker(max_per_window=1, window_seconds=60.0)
        heavy_ck = FakeRateLimitChecker(max_per_window=100, window_seconds=60.0)
        app = _RecordingApp()
        mw = GlobalRateLimitMiddleware(
            app,
            checker=global_ck,
            feature_enabled=lambda: True,
            route_checkers={"/api/v1/heavy": heavy_ck},
        )
        # /api/healthz — не matches heavy prefix → global_ck используется.
        await mw(_scope("/api/healthz"), _empty_receive, _CollectingSend())
        assert app.calls == 1
        # 2-й запрос на healthz: global_ck deny (max=1).
        send2 = _CollectingSend()
        await mw(_scope("/api/healthz"), _empty_receive, send2)
        assert app.calls == 1
        assert send2.events[0]["status"] == 429

    async def test_longest_prefix_wins(self) -> None:
        """Overlapping prefixes — самый длинный выигрывает."""
        global_ck = FakeRateLimitChecker(max_per_window=100, window_seconds=60.0)
        broad_ck = FakeRateLimitChecker(max_per_window=10, window_seconds=60.0)
        specific_ck = FakeRateLimitChecker(max_per_window=1, window_seconds=60.0)
        app = _RecordingApp()
        mw = GlobalRateLimitMiddleware(
            app,
            checker=global_ck,
            feature_enabled=lambda: True,
            route_checkers={"/api": broad_ck, "/api/v1/heavy": specific_ck},
        )
        # /api/v1/heavy/x должен match'нуть specific (longest prefix).
        await mw(_scope("/api/v1/heavy/x"), _empty_receive, _CollectingSend())
        send2 = _CollectingSend()
        await mw(_scope("/api/v1/heavy/x"), _empty_receive, send2)
        # specific_ck max=1 → 2-й запрос denied.
        assert send2.events[0]["status"] == 429


# ----------------------------- feature-flag default-OFF ---------------------


class TestFeatureFlagDefaultOff:
    async def test_pass_through_when_flag_off(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "multi_tenant_rate_limit_enabled", False)
        # feature_enabled=None → читает flag через default
        global_ck = FakeRateLimitChecker(max_per_window=1, window_seconds=60.0)
        app = _RecordingApp()
        mw = GlobalRateLimitMiddleware(app, checker=global_ck)
        # Сколько ни запрашивай — pass-through (flag OFF).
        for _ in range(5):
            await mw(_scope(), _empty_receive, _CollectingSend())
        assert app.calls == 5
