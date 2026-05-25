"""Unit-тесты GlobalRateLimitMiddleware (scaffold).

Wave: ``[wave:s16/k5-w2-global-ratelimit-mw]``.

Покрытие:
* feature_enabled=False → pass-through без вызова checker.
* allowed=True → next app вызывается.
* allowed=False → 429 + Retry-After/X-RateLimit-Remaining.
* Checker exception → fallback pass-through (не SPoF).
* FakeRateLimitChecker: bucket-логика max_per_window/window_seconds.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.entrypoints.middlewares.global_ratelimit import (
    FakeRateLimitChecker,
    GlobalRateLimitMiddleware,
    RateLimitChecker,
)


class _RecordingApp:
    """Stub-ASGI приложение, фиксирующее вызов."""

    def __init__(self) -> None:
        self.called = False
        self.scope: dict[str, Any] | None = None

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Any,
        send: Any,
    ) -> None:
        self.called = True
        self.scope = scope


async def _empty_receive() -> dict[str, Any]:
    return {"type": "http.request", "body": b"", "more_body": False}


class _RecordingSend:
    """Stub-send: накапливает события."""

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.events.append(message)


@pytest.mark.asyncio
async def test_feature_disabled_passes_through() -> None:
    """feature_enabled=False → next app вызван, checker не трогается."""
    inner = _RecordingApp()
    checker_calls: list[str] = []

    class _Recording(FakeRateLimitChecker):
        async def check(self, identifier: str) -> tuple[bool, int, int]:
            checker_calls.append(identifier)
            return True, 99, 0

    middleware = GlobalRateLimitMiddleware(
        inner,
        checker=_Recording(),
        feature_enabled=lambda: False,
    )
    send = _RecordingSend()
    await middleware(
        {"type": "http", "client": ("127.0.0.1", 0)}, _empty_receive, send
    )
    assert inner.called is True
    assert checker_calls == []


@pytest.mark.asyncio
async def test_allowed_passes_through() -> None:
    """allowed=True → next app вызывается."""
    inner = _RecordingApp()
    middleware = GlobalRateLimitMiddleware(
        inner,
        checker=FakeRateLimitChecker(max_per_window=10),
    )
    send = _RecordingSend()
    await middleware(
        {"type": "http", "client": ("1.2.3.4", 0)}, _empty_receive, send
    )
    assert inner.called is True


@pytest.mark.asyncio
async def test_blocked_returns_429() -> None:
    """allowed=False → 429 + Retry-After header."""
    inner = _RecordingApp()
    checker = FakeRateLimitChecker(max_per_window=1, window_seconds=60)
    # S18 W7: default `feature_enabled` теперь читает feature-flag
    # `multi_tenant_rate_limit_enabled` (default-OFF). Тест требует
    # активное middleware — указываем явный enable.
    middleware = GlobalRateLimitMiddleware(
        inner, checker=checker, feature_enabled=lambda: True
    )
    send = _RecordingSend()
    scope = {"type": "http", "client": ("1.2.3.4", 0)}
    # Первый — разрешён.
    await middleware(scope, _empty_receive, send)
    assert inner.called is True
    # Второй — отвергнут.
    inner.called = False
    send2 = _RecordingSend()
    await middleware(scope, _empty_receive, send2)
    assert inner.called is False
    # Должны быть события start (status=429) + body.
    starts = [e for e in send2.events if e["type"] == "http.response.start"]
    assert len(starts) == 1
    assert starts[0]["status"] == 429
    header_names = [name for name, _ in starts[0]["headers"]]
    assert b"retry-after" in header_names
    assert b"x-ratelimit-remaining" in header_names


@pytest.mark.asyncio
async def test_non_http_scope_pass_through() -> None:
    """Не-HTTP scope (lifespan/websocket) → pass-through."""
    inner = _RecordingApp()
    middleware = GlobalRateLimitMiddleware(
        inner,
        checker=FakeRateLimitChecker(),
        feature_enabled=lambda: True,
    )
    send = _RecordingSend()
    await middleware({"type": "lifespan"}, _empty_receive, send)
    assert inner.called is True


@pytest.mark.asyncio
async def test_checker_failure_falls_through() -> None:
    """Если checker падает — middleware должно пропустить запрос."""

    class _BrokenChecker:
        async def check(self, identifier: str) -> tuple[bool, int, int]:
            raise RuntimeError("Redis is down")

    inner = _RecordingApp()
    middleware = GlobalRateLimitMiddleware(
        inner, checker=_BrokenChecker(), feature_enabled=lambda: True
    )
    send = _RecordingSend()
    await middleware(
        {"type": "http", "client": ("1.2.3.4", 0)}, _empty_receive, send
    )
    # Не SPoF: запрос проходит дальше.
    assert inner.called is True


@pytest.mark.asyncio
async def test_fake_checker_window_resets() -> None:
    """FakeRateLimitChecker: после исчерпания возвращает retry_after > 0."""
    checker = FakeRateLimitChecker(max_per_window=2, window_seconds=60)
    allowed1, remaining1, _ = await checker.check("k")
    allowed2, remaining2, _ = await checker.check("k")
    allowed3, _, retry_after = await checker.check("k")
    assert allowed1 is True and allowed2 is True
    assert remaining1 == 1 and remaining2 == 0
    assert allowed3 is False
    assert retry_after >= 1


@pytest.mark.asyncio
async def test_fake_checker_protocol() -> None:
    """FakeRateLimitChecker структурно соответствует RateLimitChecker."""
    checker = FakeRateLimitChecker()
    assert isinstance(checker, RateLimitChecker)


@pytest.mark.asyncio
async def test_identifier_fn_custom() -> None:
    """Кастомный identifier_fn получает identifier (tenant) для check."""

    captured: list[str] = []

    class _Recording(FakeRateLimitChecker):
        async def check(self, identifier: str) -> tuple[bool, int, int]:
            captured.append(identifier)
            return True, 99, 0

    inner = _RecordingApp()
    middleware = GlobalRateLimitMiddleware(
        inner,
        checker=_Recording(),
        identifier_fn=lambda scope: "tenant-X",
        feature_enabled=lambda: True,
    )
    send = _RecordingSend()
    await middleware(
        {"type": "http", "client": ("1.2.3.4", 0)}, _empty_receive, send
    )
    assert captured == ["tenant-X"]
