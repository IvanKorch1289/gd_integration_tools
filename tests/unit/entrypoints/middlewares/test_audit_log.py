"""Unit tests for AuditLogMiddleware (cycle 48 pure ASGI)."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.middlewares.audit_log import AuditLogMiddleware


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok(status_code: int = 200, body: bytes = b"ok"):
    async def downstream(scope, receive, send):
        # Consume body to validate body re-injection.
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            more_body = msg.get("more_body", False)
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "POST",
    path: str = "/api",
    headers: list[tuple[bytes, bytes]] | None = None,
    state: dict | None = None,
    client: tuple[str, int] | None = ("127.0.0.1", 1234),
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": client,
        **({"state": state} if state is not None else {}),
    }


def _make_receive(body: bytes = b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


class TestAuditLogMiddleware:
    """Tests for :class:`AuditLogMiddleware` (cycle 48 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> AuditLogMiddleware:
        app = AsyncMock()
        mw = AuditLogMiddleware(app)
        mw.logger = MagicMock()
        return mw

    @pytest.mark.asyncio
    async def test_logs_and_returns_response(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """Happy path: logs audit event and returns response."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=200)
        middleware.app = app

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ) as mock_redis_provider,
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ) as mock_ch_provider,
        ):
            send = AsyncMock()
            await middleware(
                _make_scope(
                    "POST",
                    "/api",
                    headers=[
                        (b"host", b"test"),
                        (b"user-agent", b"pytest"),
                    ],
                    state={
                        "auth": type("A", (), {"principal": "client-42"})(),
                        "request_id": "req-1",
                        "correlation_id": "corr-1",
                    },
                ),
                _make_receive(b'{"x":1}'),
                send,
            )

        # logger.info был вызван.
        middleware.logger.info.assert_called()
        call_args = middleware.logger.info.call_args
        # Первый positional arg — message, второй — extra dict.
        assert call_args[0][0] == "audit_event"
        audit_event = call_args.kwargs["extra"]
        assert audit_event["method"] == "POST"
        assert audit_event["path"] == "/api"
        assert audit_event["status"] == 200
        assert audit_event["client_id"] == "client-42"
        assert audit_event["client_ip"] == "127.0.0.1"
        assert audit_event["user_agent"] == "pytest"
        assert audit_event["request_id"] == "req-1"
        assert audit_event["correlation_id"] == "corr-1"
        # payload_hash не пустой (16 hex chars из SHA256).
        assert len(audit_event["payload_hash"]) == 16

    @pytest.mark.asyncio
    async def test_uses_cached_body(self, middleware: AuditLogMiddleware) -> None:
        """Uses state['body'] (set by RequestBodyCacheMiddleware)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            await middleware(
                _make_scope("POST", "/api", state={"body": b"cached"}),
                _make_receive(b"ignored"),
                send,
            )

        call_args = middleware.logger.info.call_args
        audit_event = call_args.kwargs["extra"]
        # payload_hash из cached body (не из receive).
        from src.backend.entrypoints.middlewares import _body_hash
        assert audit_event["payload_hash"] == _body_hash.payload_hash(
            b"cached", prefix_len=16
        )

    @pytest.mark.asyncio
    async def test_body_read_failure_graceful(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """Pure ASGI: graceful fallback когда body read fails (http.disconnect)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        # Receive returns http.disconnect immediately (no body).
        async def disconnect_receive():
            return {"type": "http.disconnect"}

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            await middleware(
                _make_scope("POST", "/api"),
                disconnect_receive,
                send,
            )

        # 200 — audit emit'd даже без body.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_redis_failure_ignored(self, middleware: AuditLogMiddleware) -> None:
        """Redis stream error is silently ignored."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        redis_mock = AsyncMock()
        redis_mock.add_to_stream.side_effect = ConnectionError("redis down")

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=redis_mock,
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            # Должен НЕ raise — audit failure silent.
            await middleware(
                _make_scope("GET", "/api"),
                _make_receive(),
                send,
            )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_clickhouse_failure_ignored(
        self, middleware: AuditLogMiddleware
    ) -> None:
        """ClickHouse insert error is silently ignored."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        ch_mock = AsyncMock()
        ch_mock.insert.side_effect = Exception("ch down")

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=ch_mock,
            ),
        ):
            send = AsyncMock()
            # Должен НЕ raise.
            await middleware(
                _make_scope("GET", "/api"),
                _make_receive(),
                send,
            )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200

    @pytest.mark.asyncio
    async def test_no_client_defaults(self, middleware: AuditLogMiddleware) -> None:
        """Missing client → 'unknown' IP."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        middleware.app = app

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            # Без 'client' в scope.
            await middleware(
                _make_scope("GET", "/api", client=None),
                _make_receive(),
                send,
            )

        call_args = middleware.logger.info.call_args
        audit_event = call_args.kwargs["extra"]
        assert audit_event["client_ip"] == "unknown"

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без audit."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = AuditLogMiddleware(app=app)
        mw.logger = MagicMock()

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        # websocket.accept прошёл, logger НЕ вызван.
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)
        mw.logger.info.assert_not_called()

    @pytest.mark.asyncio
    async def test_downstream_consumes_replayed_body(self) -> None:
        """Cycle 48 invariant: downstream прочитывает body через replay_receive."""
        captured_body = {}

        async def downstream(scope, receive, send):
            body_bytes = b""
            more_body = True
            while more_body:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    break
                body_bytes += msg.get("body", b"")
                more_body = msg.get("more_body", False)
            captured_body["body"] = body_bytes
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = AuditLogMiddleware(app=app)
        mw.logger = MagicMock()

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            await mw(
                _make_scope("POST", "/api"),
                _make_receive(b"audit-payload"),
                send,
            )

        # Downstream прочитал body через replay.
        assert captured_body["body"] == b"audit-payload"

    @pytest.mark.asyncio
    async def test_query_string_in_audit_event(self) -> None:
        """Query string извлекается из ASGI scope и добавляется в audit."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditLogMiddleware(app=app)
        mw.logger = MagicMock()

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            scope = _make_scope("GET", "/api")
            scope["query_string"] = b"foo=bar&baz=qux"
            await mw(scope, _make_receive(), send)

        call_args = mw.logger.info.call_args
        audit_event = call_args.kwargs["extra"]
        assert audit_event["query"] == "foo=bar&baz=qux"

    @pytest.mark.asyncio
    async def test_anonymous_client_id(self) -> None:
        """Без auth context → client_id='anonymous'."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditLogMiddleware(app=app)
        mw.logger = MagicMock()

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            await mw(
                _make_scope("GET", "/api"),  # no state['auth']
                _make_receive(),
                send,
            )

        call_args = mw.logger.info.call_args
        audit_event = call_args.kwargs["extra"]
        assert audit_event["client_id"] == "anonymous"

    @pytest.mark.asyncio
    async def test_does_not_break_request_on_audit_failure(self) -> None:
        """Cycle 48 invariant: audit emit error НЕ ломает request."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditLogMiddleware(app=app)
        mw.logger = MagicMock()
        mw.logger.info.side_effect = RuntimeError("logger bug")

        with (
            patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ),
            patch(
                "src.backend.core.di.providers.get_clickhouse_client_provider",
                return_value=AsyncMock(),
            ),
        ):
            send = AsyncMock()
            # Должен НЕ raise — logger bug logged, не propagated.
            await mw(
                _make_scope("GET", "/api"),
                _make_receive(),
                send,
            )

        # 200 — request не сломан.
        start = _start_message(send)
        assert start is not None
        assert start["status"] == 200
