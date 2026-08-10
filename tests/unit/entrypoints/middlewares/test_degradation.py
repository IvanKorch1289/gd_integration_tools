"""Unit tests for DegradationMiddleware (cycle 42 pure ASGI)."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.resilience.degradation import DegradationMode
from src.backend.entrypoints.middlewares.degradation import DegradationMiddleware


class FakeStatus:
    """Fake component status for degradation tests."""

    def __init__(self, last_used_backend: str, degradation: str) -> None:
        self.last_used_backend = last_used_backend
        self.degradation = degradation


def _start_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock) -> dict | None:
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _start_headers(send: AsyncMock) -> dict[bytes, bytes]:
    start = _start_message(send)
    if start is None:
        return {}
    return dict(start.get("headers", []))


def _downstream_ok():
    """Downstream возвращающий 200 OK."""
    async def downstream(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    return downstream


def _make_scope(
    method: str = "POST", path: str = "/api/v1/users",
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": [(b"host", b"test")],
    }


class TestDegradationMiddleware:
    """Tests for :class:`DegradationMiddleware` (cycle 42 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> DegradationMiddleware:
        return DegradationMiddleware(AsyncMock(), retry_after=30)

    @pytest.mark.asyncio
    async def test_full_mode_passes_through(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """FULL mode allows all requests."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.FULL
            await mw(_make_scope("POST", "/api/v1/users"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_maintenance_blocks_non_essential(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """MAINTENANCE mode blocks non-maintenance paths."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            await mw(_make_scope("GET", "/api/v1/users"), AsyncMock(), send)

        # 503 через send.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        headers = _start_headers(send)
        assert headers[b"retry-after"] == b"30"
        assert headers[b"x-degradation-mode"] == b"maintenance"

        # Body — JSON с reason.
        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["status"] == "degraded"

    @pytest.mark.asyncio
    async def test_maintenance_allows_liveness(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """MAINTENANCE mode allows /health/liveness."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            await mw(_make_scope("GET", "/health/liveness"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_essential_only_blocks_api(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """ESSENTIAL_ONLY blocks /api paths."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.ESSENTIAL_ONLY
            await mw(_make_scope("GET", "/api/v1/users"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_cache_only_blocks_writes(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """CACHE_ONLY blocks POST/PUT/PATCH/DELETE."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.CACHE_ONLY
            await mw(_make_scope("POST", "/api/v1/users"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        headers = _start_headers(send)
        assert headers[b"x-degradation-mode"] == b"cache-only-no-writes"

    @pytest.mark.asyncio
    async def test_cache_only_allows_reads_and_sets_header(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """CACHE_ONLY allows GET и инжектит X-Degradation-Mode header."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.CACHE_ONLY
            await mw(_make_scope("GET", "/api/v1/users"), AsyncMock(), send)

        # 200 от downstream.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
        # X-Degradation-Mode header добавлен через send-wrapper.
        headers = _start_headers(send)
        assert headers[b"x-degradation-mode"] == b"cache_only"

    @pytest.mark.asyncio
    async def test_read_only_blocks_writes(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """READ_ONLY blocks writes."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.READ_ONLY
            await mw(_make_scope("DELETE", "/api/v1/users/1"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        headers = _start_headers(send)
        assert headers[b"x-degradation-mode"] == b"read-only"

    @pytest.mark.asyncio
    async def test_bypass_prefixes(self, middleware: DegradationMiddleware) -> None:
        """Bypass prefixes allow writes even in degraded mode."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.READ_ONLY
            await mw(_make_scope("POST", "/api/v1/audit/events"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_legacy_db_main_fallback_blocks(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """Legacy path: db_main in fallback blocks writes."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with (
            patch(
                "src.backend.core.resilience.degradation.degradation_manager",
            ) as mock_mgr,
            patch(
                "src.backend.core.di.providers.get_resilience_coordinator_provider",
            ) as mock_coord_provider,
        ):
            mock_mgr.current_mode = DegradationMode.FULL
            mock_coord = MagicMock()
            mock_coord.status.return_value = {
                "db_main": FakeStatus("sqlite_ro", "degraded"),
            }
            mock_coord_provider.return_value = mock_coord

            await mw(_make_scope("POST", "/api/v1/users"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503
        # Body содержит информацию о заблокированных компонентах.
        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))
        assert "db_main" in parsed["reason"]

    @pytest.mark.asyncio
    async def test_legacy_db_main_primary_allows(
        self, middleware: DegradationMiddleware,
    ) -> None:
        """Legacy path: db_main on primary allows writes."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with (
            patch(
                "src.backend.core.resilience.degradation.degradation_manager",
            ) as mock_mgr,
            patch(
                "src.backend.core.di.providers.get_resilience_coordinator_provider",
            ) as mock_coord_provider,
        ):
            mock_mgr.current_mode = DegradationMode.FULL
            mock_coord = MagicMock()
            mock_coord.status.return_value = {
                "db_main": FakeStatus("primary", "healthy"),
            }
            mock_coord_provider.return_value = mock_coord

            await mw(_make_scope("POST", "/api/v1/users"), AsyncMock(), send)

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200


class TestDegradationMiddlewarePureASGI:
    """Cycle 42: pure ASGI regression-тесты для DegradationMiddleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без degradation check."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_503_body_contains_required_fields(self) -> None:
        """503 response body содержит status, reason, retry_after_seconds."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            await mw(
                _make_scope("GET", "/api/v1/users"),
                AsyncMock(),
                send,
            )

        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert "status" in parsed
        assert "reason" in parsed
        assert "retry_after_seconds" in parsed
        assert parsed["status"] == "degraded"
        assert parsed["retry_after_seconds"] == 30

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_when_blocked(self) -> None:
        """При blocked mode downstream НЕ вызывается (cycle 42 invariant)."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise AssertionError("downstream НЕ должен быть вызван")

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.MAINTENANCE
            await mw(
                _make_scope("GET", "/api/v1/users"),
                AsyncMock(),
                send,
            )

        # 503 отправлен (если бы downstream был вызван, тест упал бы).
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 503

    @pytest.mark.asyncio
    async def test_send_wrapper_overrides_existing_mode_header(self) -> None:
        """send-wrapper перезаписывает existing X-Degradation-Mode header."""
        # Downstream устанавливает СВОЙ X-Degradation-Mode — наш wrapper
        # должен перезаписать (наш middleware — source of truth).
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"x-degradation-mode", b"stale-downstream-value"),
                    ],
                },
            )
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream
        mw = DegradationMiddleware(app, retry_after=30)

        send = AsyncMock()
        with patch(
            "src.backend.core.resilience.degradation.degradation_manager",
        ) as mock_mgr:
            mock_mgr.current_mode = DegradationMode.CACHE_ONLY
            await mw(
                _make_scope("GET", "/api/v1/users"),
                AsyncMock(),
                send,
            )

        headers = _start_headers(send)
        # Наш value (mode.value="cache_only") — НЕ downstream value.
        assert headers[b"x-degradation-mode"] == b"cache_only"

    def test_is_bypassed(self) -> None:
        """_is_bypassed проверяет prefix correctly."""
        from src.backend.entrypoints.middlewares.degradation import (
            DEGRADATION_BYPASS_PREFIXES,
        )

        assert any(p == "/health" for p in DEGRADATION_BYPASS_PREFIXES)
        assert any(p == "/api/v1/audit" for p in DEGRADATION_BYPASS_PREFIXES)
