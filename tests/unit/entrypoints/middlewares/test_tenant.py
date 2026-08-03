"""Unit tests for TenantMiddleware (cycle 38 — pure ASGI)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestTenantMiddleware:
    """Tests for :class:`TenantMiddleware` (cycle 38 pure ASGI)."""

    @pytest.fixture
    def middleware(self):
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        return TenantMiddleware(AsyncMock(), default_tenant="default")

    def _make_downstream(
        self, tenant_id_to_set: str | None = None, *, with_state_tenant: str | None = None
    ):
        """Создаёт downstream app, возвращающий 200 + empty body.

        Опционально устанавливает ``state['tenant_id']`` (имитация auth
        middleware, который мог установить tenant_id раньше).
        """
        async def downstream(scope, receive, send):
            if with_state_tenant is not None:
                scope.setdefault("state", {})["tenant_id"] = with_state_tenant
            await send(
                {"type": "http.response.start", "status": 200, "headers": []}
            )
            await send({"type": "http.response.body", "body": b"ok"})

        return downstream

    def _start_headers(self, send_mock: AsyncMock) -> dict[bytes, bytes]:
        """Извлекает headers из http.response.start."""
        for call in send_mock.await_args_list:
            msg = call.args[0]
            if msg["type"] == "http.response.start":
                return dict(msg.get("headers", []))
        return {}

    @pytest.mark.asyncio
    async def test_header_tenant_used(self) -> None:
        """X-Tenant-ID header извлекается и emit'ится в response."""
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        app = AsyncMock()
        app.side_effect = self._make_downstream()

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            mw = TenantMiddleware(app, default_tenant="default")
            send = AsyncMock()
            await mw(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api",
                    "headers": [
                        (b"host", b"test"),
                        (b"x-tenant-id", b"tenant-42"),
                    ],
                },
                AsyncMock(),
                send,
            )

        headers = self._start_headers(send)
        assert headers[b"x-tenant-id"] == b"tenant-42"
        mock_setter.assert_called_once_with(tenant_id="tenant-42")

    @pytest.mark.asyncio
    async def test_state_tenant_fallback(self) -> None:
        """Если нет header — используется state['tenant_id'] (от auth middleware)."""
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        app = AsyncMock()
        # Downstream устанавливает state['tenant_id'] (как auth middleware).
        async def downstream(scope, receive, send):
            scope.setdefault("state", {})["tenant_id"] = "state-tenant"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            mw = TenantMiddleware(app, default_tenant="default")
            send = AsyncMock()
            await mw(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api",
                    "headers": [(b"host", b"test")],
                },
                AsyncMock(),
                send,
            )

        headers = self._start_headers(send)
        assert headers[b"x-tenant-id"] == b"state-tenant"
        mock_setter.assert_called_once_with(tenant_id="state-tenant")

    @pytest.mark.asyncio
    async def test_default_tenant_fallback(self) -> None:
        """Если нет header и нет state — default tenant."""
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        app = AsyncMock()
        app.side_effect = self._make_downstream()

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            mw = TenantMiddleware(app, default_tenant="default")
            send = AsyncMock()
            await mw(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api",
                    "headers": [(b"host", b"test")],
                },
                AsyncMock(),
                send,
            )

        headers = self._start_headers(send)
        assert headers[b"x-tenant-id"] == b"default"
        mock_setter.assert_called_once_with(tenant_id="default")

    @pytest.mark.asyncio
    async def test_header_priority_over_state(self) -> None:
        """Header X-Tenant-ID имеет приоритет над state['tenant_id']."""
        from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

        app = AsyncMock()
        # Downstream устанавливает state['tenant_id'] (НО header должен выиграть).
        async def downstream(scope, receive, send):
            scope.setdefault("state", {})["tenant_id"] = "state-tenant"
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app.side_effect = downstream

        mock_setter = MagicMock()
        with patch(
            "src.backend.entrypoints.middlewares.tenant.get_correlation_context_setter_provider",
            return_value=lambda **kwargs: mock_setter(**kwargs),
        ):
            mw = TenantMiddleware(app, default_tenant="default")
            send = AsyncMock()
            await mw(
                {
                    "type": "http",
                    "method": "GET",
                    "path": "/api",
                    "headers": [
                        (b"host", b"test"),
                        (b"x-tenant-id", b"header-tenant"),
                    ],
                },
                AsyncMock(),
                send,
            )

        headers = self._start_headers(send)
        assert headers[b"x-tenant-id"] == b"header-tenant"
        mock_setter.assert_called_once_with(tenant_id="header-tenant")
