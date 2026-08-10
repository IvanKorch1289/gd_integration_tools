"""Unit tests for AuditReplayMiddleware (cycle 45 pure ASGI)."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from src.backend.entrypoints.middlewares.audit_replay import (
    AuditReplayMiddleware,
    list_audit_records,
    replay_audit_record,
)


def _downstream_ok(status_code: int = 200, body: bytes = b"ok"):
    """Downstream возвращающий 200 OK (или заданный status)."""
    async def downstream(scope, receive, send):
        # Consume body from receive (validates body re-injection).
        body_bytes = b""
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            body_bytes += msg.get("body", b"")
            more_body = msg.get("more_body", False)
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "POST",
    path: str = "/api/v1/users",
    headers: list[tuple[bytes, bytes]] | None = None,
    state: dict | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
        **({"state": state} if state is not None else {}),
    }


def _make_receive(body: bytes):
    """ASGI receive callable возвращающая body chunk."""
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


class TestAuditReplayMiddleware:
    """Tests for :class:`AuditReplayMiddleware` (cycle 45 pure ASGI)."""

    @pytest.fixture
    def middleware(self) -> AuditReplayMiddleware:
        return AuditReplayMiddleware(AsyncMock())

    @pytest.mark.asyncio
    async def test_skip_paths(self, middleware: AuditReplayMiddleware) -> None:
        """Health-like paths are skipped (без audit)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        send = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
        ):
            await mw(
                _make_scope("GET", "/health"),
                _make_receive(b""),
                send,
            )

        # 200 от downstream (без audit).
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "http.response.start" for m in msgs)

    @pytest.mark.asyncio
    async def test_sampling_excludes(self, middleware: AuditReplayMiddleware) -> None:
        """Sample rate = 0 → запрос пробрасывается без audit."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)
        mw._sample_rate = 0.0

        send = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
        ):
            await mw(
                _make_scope("GET", "/api/v1/users"),
                _make_receive(b""),
                send,
            )

        # Downstream отработал (200 OK).
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(
            m["type"] == "http.response.start" and m["status"] == 200
            for m in msgs
        )

    @pytest.mark.asyncio
    async def test_audit_record_sent(self, middleware: AuditReplayMiddleware) -> None:
        """Happy path: audit record отправляется в Redis stream."""
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=201)
        mw = AuditReplayMiddleware(app)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            send = AsyncMock()
            await mw(
                _make_scope(
                    "POST",
                    "/api/v1/users",
                    headers=[
                        (b"host", b"test"),
                        (b"x-correlation-id", b"corr-1"),
                    ],
                ),
                _make_receive(b'{"x":1}'),
                send,
            )

        # Redis stream вызван с правильными args.
        redis_mock.add_to_stream.assert_awaited_once()
        call_args = redis_mock.add_to_stream.await_args
        assert call_args is not None
        assert call_args.kwargs["stream_name"] == "audit:requests"
        entry = call_args.kwargs["data"]
        assert entry["method"] == "POST"
        assert entry["path"] == "/api/v1/users"
        assert entry["status_code"] == 201
        assert entry["correlation_id"] == "corr-1"
        assert entry["client_ip"] == "127.0.0.1"
        assert entry["request_body"] == '{"x":1}'

    @pytest.mark.asyncio
    async def test_uses_cached_body(self, middleware: AuditReplayMiddleware) -> None:
        """IL-OBS1: использует state['body'] если cached (от RequestBodyCache)."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            send = AsyncMock()
            await mw(
                _make_scope("POST", "/api", state={"body": b"cached-body"}),
                _make_receive(b"ignored"),  # receive() вернёт b"ignored" НО
                # state['body'] имеет приоритет.
                send,
            )

        entry = redis_mock.add_to_stream.await_args.kwargs["data"]
        assert entry["request_body"] == "cached-body"

    @pytest.mark.asyncio
    async def test_redis_unavailable(self, middleware: AuditReplayMiddleware) -> None:
        """Redis недоступен — middleware не падает, request проходит."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        redis_mock = AsyncMock()
        redis_mock.add_to_stream.side_effect = ConnectionError("redis down")

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            send = AsyncMock()
            # Должен НЕ raise — audit failures non-blocking.
            await mw(
                _make_scope("GET", "/api"),
                _make_receive(b""),
                send,
            )

        # Downstream отработал.
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(
            m["type"] == "http.response.start" and m["status"] == 200
            for m in msgs
        )

    @pytest.mark.asyncio
    async def test_body_truncation(self, middleware: AuditReplayMiddleware) -> None:
        """Body > 8KB → truncated до 8192 chars."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            send = AsyncMock()
            await mw(
                _make_scope("POST", "/api"),
                _make_receive(b"x" * 10000),
                send,
            )

        entry = redis_mock.add_to_stream.await_args.kwargs["data"]
        # Body truncated до 8192.
        assert len(entry["request_body"]) == 8192

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self) -> None:
        """Non-HTTP scope (websocket) пробрасывается без audit."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = AuditReplayMiddleware(app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/api", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_downstream_consumes_replayed_body(self) -> None:
        """Cycle 45 critical: downstream должен прочитать body через replay_receive."""
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
        mw = AuditReplayMiddleware(app)

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=AsyncMock(),
        ):
            send = AsyncMock()
            await mw(
                _make_scope("POST", "/api"),
                _make_receive(b"important-payload"),
                send,
            )

        # Downstream прочитал body через replay (не через _receive).
        assert captured_body["body"] == b"important-payload"

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_request(self) -> None:
        """Cycle 45 invariant: audit error → request всё равно проходит."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        # Make _audit raise (simulating internal bug).
        with patch.object(
            mw, "_audit", side_effect=RuntimeError("audit bug")
        ):
            send = AsyncMock()
            with patch(
                "src.backend.core.di.providers.get_redis_stream_client_provider",
                return_value=AsyncMock(),
            ):
                # Должен НЕ raise — audit error logged, not propagated.
                await mw(
                    _make_scope("GET", "/api"),
                    _make_receive(b""),
                    send,
                )

        # 200 от downstream (audit failed silently).
        msgs = [c.args[0] for c in send.await_args_list]
        assert any(
            m["type"] == "http.response.start" and m["status"] == 200
            for m in msgs
        )

    @pytest.mark.asyncio
    async def test_query_string_in_audit_entry(self) -> None:
        """Query string записывается в audit entry."""
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AuditReplayMiddleware(app)

        redis_mock = AsyncMock()
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            send = AsyncMock()
            scope = _make_scope("GET", "/api")
            scope["query_string"] = b"foo=bar&baz=qux"
            await mw(
                scope,
                _make_receive(b""),
                send,
            )

        entry = redis_mock.add_to_stream.await_args.kwargs["data"]
        assert entry["query"] == "foo=bar&baz=qux"


class TestListAuditRecords:
    """Tests for :func:`list_audit_records`."""

    @pytest.mark.asyncio
    async def test_returns_records(self) -> None:
        """Happy path: returns list of records."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = [{"id": "1", "path": "/api"}]

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            records = await list_audit_records(count=10)

        assert records == [{"id": "1", "path": "/api"}]
        redis_mock.read_stream.assert_awaited_once_with(
            stream_name="audit:requests", count=10, start_id="-"
        )

    @pytest.mark.asyncio
    async def test_returns_empty_on_error(self) -> None:
        """Returns empty list on any exception."""
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            side_effect=Exception("fail"),
        ):
            records = await list_audit_records()

        assert records == []


class TestReplayAuditRecord:
    """Tests for :func:`replay_audit_record`."""

    @pytest.mark.asyncio
    async def test_record_found(self) -> None:
        """Returns record data when found."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = [
            {"method": "POST", "path": "/api", "request_body": "{}"}
        ]

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "ready_for_replay"
        assert result["record_id"] == "123"
        assert result["method"] == "POST"

    @pytest.mark.asyncio
    async def test_record_not_found(self) -> None:
        """Returns error when record not found."""
        redis_mock = AsyncMock()
        redis_mock.read_stream.return_value = []

        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            return_value=redis_mock,
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "error"
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_error_on_read(self) -> None:
        """Returns error on Redis exception."""
        with patch(
            "src.backend.core.di.providers.get_redis_stream_client_provider",
            side_effect=Exception("fail"),
        ):
            result = await replay_audit_record("123")

        assert result["status"] == "error"
        assert "fail" in result["error"]
