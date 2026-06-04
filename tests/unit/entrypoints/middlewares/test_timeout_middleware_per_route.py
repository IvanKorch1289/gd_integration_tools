"""Unit-тесты per-route :class:`TimeoutMiddleware` (S18 W6).

Покрытие:
    * Flag OFF → legacy behaviour (single global timeout).
    * Flag ON + match → per-route timeout применяется.
    * Flag ON + no match → fallback на global default.
    * Longest-prefix wins (advisor pt 3): /api/v1/heavy выигрывает у /api.
    * Empty registry / None → всегда global default.
    * Timeout exceeded → JSONResponse 408.
"""

# ruff: noqa: S101

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.config.features import feature_flags
from src.backend.core.config.settings import settings
from src.backend.entrypoints.middlewares.timeout import TimeoutMiddleware


@pytest.fixture(autouse=True)
def _cancel_pending_asyncio_tasks():
    yield
    try:
        loop = asyncio.get_running_loop()
        for task in asyncio.all_tasks(loop):
            if not task.done():
                task.cancel()
    except RuntimeError:
        pass


def _build_app(
    *, route_timeouts: dict[str, float] | None = None, sleep_seconds: float = 0.0
) -> FastAPI:
    """FastAPI с TimeoutMiddleware и endpoints с регулируемым sleep."""
    app = FastAPI()
    app.add_middleware(TimeoutMiddleware, route_timeouts=route_timeouts)

    @app.get("/api/healthz")
    async def healthz() -> dict:
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)
        return {"status": "ok"}

    @app.get("/api/v1/heavy/process")
    async def heavy() -> dict:
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)
        return {"result": "done"}

    @app.get("/api/v1/users/me")
    async def users() -> dict:
        if sleep_seconds > 0:
            await asyncio.sleep(sleep_seconds)
        return {"user": "alice"}

    return app


# ----------------------------- flag-OFF baseline ---------------------------


class TestFeatureFlagDisabled:
    """default-OFF: single global timeout, registry игнорируется."""

    def test_pass_through_with_global_timeout(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", False)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        # Передаём registry, но flag OFF — он игнорируется
        app = _build_app(route_timeouts={"/api/v1/heavy": 0.01})
        client = TestClient(app)
        resp = client.get("/api/v1/heavy/process")
        # Sleep=0 → быстрый ответ, не timeout (т.к. global=5.0).
        assert resp.status_code == 200


# ----------------------------- per-route lookup ----------------------------


class TestPerRouteLookup:
    """Flag ON: per-route registry применяется через longest-prefix-match."""

    def test_match_applies_per_route_total(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        # heavy: 0.05s budget; endpoint sleeps 0.5s → должен timeout-нуться.
        app = _build_app(route_timeouts={"/api/v1/heavy": 0.05}, sleep_seconds=0.5)
        client = TestClient(app)
        resp = client.get("/api/v1/heavy/process")
        assert resp.status_code == 408
        assert "Превышено" in resp.json()["detail"]

    def test_no_match_falls_back_to_global(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        # /api/healthz не matches /api/v1/heavy prefix → global=5.0s.
        app = _build_app(route_timeouts={"/api/v1/heavy": 0.05}, sleep_seconds=0.0)
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code == 200  # быстрый ответ, global default OK

    def test_longest_prefix_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """advisor pt 3: longest-prefix-match при overlapping prefixes."""
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        # Два prefix'а: общий /api (5.0s) и специфичный /api/v1/heavy (0.05s).
        # Endpoint /api/v1/heavy/process должен match'нуть /api/v1/heavy.
        app = _build_app(
            route_timeouts={"/api": 5.0, "/api/v1/heavy": 0.05}, sleep_seconds=0.5
        )
        client = TestClient(app)
        resp = client.get("/api/v1/heavy/process")
        # Longest prefix /api/v1/heavy выигрывает (0.05s) → 408.
        assert resp.status_code == 408

    def test_empty_registry_uses_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        app = _build_app(route_timeouts={}, sleep_seconds=0.0)
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code == 200

    def test_none_registry_uses_global(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", True)
        monkeypatch.setattr(settings.secure, "request_timeout", 5.0)
        app = _build_app(route_timeouts=None, sleep_seconds=0.0)
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code == 200


# ----------------------------- timeout exceeded ----------------------------


class TestTimeoutExceededResponse:
    """Превышение лимита → 408 JSON."""

    def test_global_timeout_exceeded_returns_408(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(feature_flags, "per_route_timeout_enabled", False)
        monkeypatch.setattr(settings.secure, "request_timeout", 0.05)
        app = _build_app(sleep_seconds=0.5)
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code == 408
        body = resp.json()
        assert "Превышено" in body["detail"]
