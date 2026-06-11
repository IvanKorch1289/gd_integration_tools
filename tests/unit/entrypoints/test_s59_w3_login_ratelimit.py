"""Tests для S59 W3 — Rate limiting для /auth/login.

Coverage:
* IP-based rate limit (5/min default);
* Username-based rate limit (3/5min default);
* X-Forwarded-For honoured (за reverse proxy);
* Tarpit delay при exceeded;
* Fail-secure (Redis unavailable → 503);
* Integration: real endpoint /auth/login с mock limiter.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.dependencies.login_ratelimit import (
    IP_LIMIT,
    IP_WINDOW_SECONDS,
    TARPIT_DELAY_SECONDS,
    USERNAME_LIMIT,
    USERNAME_WINDOW_SECONDS,
    LoginRateLimitExceeded,
    check_ip_rate_limit,
    check_username_rate_limit,
)

# === IP limit tunables ===


def test_ip_limit_constants() -> None:
    """IP limit = 5 attempts / 60s window."""
    assert IP_LIMIT == 5
    assert IP_WINDOW_SECONDS == 60


def test_username_limit_constants() -> None:
    """Username limit = 3 attempts / 300s window."""
    assert USERNAME_LIMIT == 3
    assert USERNAME_WINDOW_SECONDS == 300


def test_tarpit_delay_positive() -> None:
    """Tarpit delay = 1 second (замедляет brute-force)."""
    assert TARPIT_DELAY_SECONDS >= 1.0


# === X-Forwarded-For parsing (via _extract_client_ip internals) ===


def _build_request(
    headers: dict[str, str] | None = None, client_host: str = "1.2.3.4"
) -> Request:
    """Build minimal Request mock for _extract_client_ip testing."""
    from starlette.datastructures import Headers

    req = MagicMock(spec=Request)
    req.headers = Headers(headers or {})
    req.client = MagicMock()
    req.client.host = client_host
    return req


async def test_xff_first_ip_used() -> None:
    """X-Forwarded-For → первый IP (real client за proxy)."""
    from src.backend.entrypoints.api.v1.dependencies.login_ratelimit import (
        _extract_client_ip,
    )

    req = _build_request(
        headers={"x-forwarded-for": "10.0.0.1, 192.168.1.1, 172.16.0.1"},
        client_host="127.0.0.1",
    )
    ip = await _extract_client_ip(req)
    assert ip == "10.0.0.1"


async def test_direct_connection_fallback() -> None:
    """Без XFF → request.client.host."""
    from src.backend.entrypoints.api.v1.dependencies.login_ratelimit import (
        _extract_client_ip,
    )

    req = _build_request(headers={}, client_host="5.6.7.8")
    ip = await _extract_client_ip(req)
    assert ip == "5.6.7.8"


# === check_ip_rate_limit — mocked limiter ===


async def test_check_ip_rate_limit_ok() -> None:
    """OK: limiter returns remaining > 0 → no exception."""
    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(
        return_value={"remaining": 3, "reset_at": 0, "limit": 5}
    )

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        req = _build_request(client_host="1.2.3.4")
        # Should not raise
        await check_ip_rate_limit(req)


async def test_check_ip_rate_limit_exceeded_raises_429() -> None:
    """Exceeded: limiter raises RateLimitExceeded → LoginRateLimitExceeded (429)."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimitExceeded,
    )

    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(
        side_effect=RateLimitExceeded(limit=5, window=60, retry_after=42)
    )

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        req = _build_request(client_host="9.9.9.9")
        with pytest.raises(LoginRateLimitExceeded) as exc_info:
            await check_ip_rate_limit(req)
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 42
        assert "Retry-After" in exc_info.value.headers


async def test_check_ip_rate_limit_backend_unavailable_503() -> None:
    """Redis unavailable → 503 (fail-secure), НЕ fail-open."""
    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(side_effect=RuntimeError("redis connection refused"))

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        req = _build_request(client_host="5.5.5.5")
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            await check_ip_rate_limit(req)
        assert exc_info.value.status_code == 503


# === check_username_rate_limit — mocked limiter ===


async def test_check_username_rate_limit_empty_username_skipped() -> None:
    """Empty username → skip check (no identifier)."""
    # Should NOT raise, no limiter interaction
    await check_username_rate_limit("")


async def test_check_username_rate_limit_ok() -> None:
    """OK case для username check."""
    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(
        return_value={"remaining": 2, "reset_at": 0, "limit": 3}
    )

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        await check_username_rate_limit("alice")


async def test_check_username_rate_limit_exceeded() -> None:
    """Exceeded username check → 429."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimitExceeded,
    )

    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(
        side_effect=RateLimitExceeded(limit=3, window=300, retry_after=120)
    )

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        with pytest.raises(LoginRateLimitExceeded) as exc_info:
            await check_username_rate_limit("bob")
        assert exc_info.value.status_code == 429


# === Integration: real endpoint /auth/login with rate limit mock ===


@pytest.fixture
def mock_limiter() -> MagicMock:
    """Mock rate limiter (все запросы OK)."""
    limiter = MagicMock()
    limiter.check = AsyncMock(return_value={"remaining": 5, "reset_at": 0, "limit": 5})
    return limiter


@pytest.fixture
def integration_client(mock_limiter: MagicMock) -> Any:
    """FastAPI TestClient с mocked rate limiter."""

    from src.backend.entrypoints.api.v1.endpoints.auth_login import router

    app = FastAPI()
    app.include_router(router, prefix="/auth")

    with patch(
        "src.backend.entrypoints.api.v1.dependencies.login_ratelimit._check_rate_limit",
        return_value=(True, 5),
    ):
        # Создаём client внутри patch context
        yield TestClient(app)


def test_login_endpoint_includes_ip_rate_limit_dependency(
    integration_client: Any,
) -> None:
    """POST /auth/login использует check_ip_rate_limit (через endpoint dependencies)."""
    # Проверяем что router имеет dependency registered
    from src.backend.entrypoints.api.v1.endpoints.auth_login import router

    # Находим login route (router path может быть /auth/login если prefix
    # применён на import side, или /login если prefix применяется при register)
    login_route = None
    for route in router.routes:
        path = getattr(route, "path", "") or ""
        methods = str(getattr(route, "methods", ""))
        if path.endswith("/login") and "POST" in methods:
            login_route = route
            break
    assert login_route is not None, (
        f"POST /login route not found. Routes: "
        f"{[(r.path, r.methods) for r in router.routes]}"
    )

    # Проверяем dependencies содержат check_ip_rate_limit
    deps = getattr(login_route, "dependencies", []) or []
    # deps = list of Depends() instances
    dep_strings = [str(d) for d in deps]
    # "check_ip_rate_limit" должно быть в строковом представлении
    assert any("check_ip_rate_limit" in s for s in dep_strings), (
        f"check_ip_rate_limit not in deps. Deps: {dep_strings}"
    )


# === Tarpit delay timing test (fast, 0.01 sec в тестах) ===


async def test_tarpit_delays_response_on_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При exceeded — asyncio.sleep с TARPIT_DELAY_SECONDS."""
    from src.backend.infrastructure.resilience.unified_rate_limiter import (
        RateLimitExceeded,
    )

    # Override tarpit delay для test speed
    monkeypatch.setattr(
        "src.backend.entrypoints.api.v1.dependencies.login_ratelimit.TARPIT_DELAY_SECONDS",
        0.01,
    )

    mock_limiter = MagicMock()
    mock_limiter.check = AsyncMock(
        side_effect=RateLimitExceeded(limit=5, window=60, retry_after=1)
    )

    sleep_called: list[float] = []
    real_sleep = asyncio.sleep

    async def mock_sleep(delay: float) -> None:
        sleep_called.append(delay)
        await real_sleep(0)  # minimal yield

    monkeypatch.setattr(
        "src.backend.entrypoints.api.v1.dependencies.login_ratelimit.asyncio.sleep",
        mock_sleep,
    )

    with patch(
        "src.backend.infrastructure.resilience.unified_rate_limiter.get_rate_limiter",
        return_value=mock_limiter,
    ):
        req = _build_request(client_host="1.1.1.1")
        with pytest.raises(LoginRateLimitExceeded):
            await check_ip_rate_limit(req)

    # Sleep должен быть вызван с tarpit delay
    assert len(sleep_called) >= 1
    assert sleep_called[0] == 0.01  # patched value
