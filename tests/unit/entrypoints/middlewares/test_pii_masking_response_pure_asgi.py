"""Pure ASGI regression-тесты для PIIMaskingResponseMiddleware (cycle 54)."""


from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.pii_masking_response import (
    PIIMaskingResponseMiddleware,
)


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _body_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.body":
            return msg
    return None


def _downstream_json(body: bytes, status: int = 200):
    """Downstream возвращающий JSON response с заданным body."""
    async def downstream(scope, receive, send):
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return downstream


def _make_scope(
    method: str = "GET",
    path: str = "/api/users/me",
    state: dict | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": [],
        "query_string": b"",
        **({"state": state} if state is not None else {}),
    }


def _make_receive():
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}
    return receive


class TestPIIMaskingResponseMiddlewarePureASGI:
    """Cycle 54: pure ASGI regression-тесты для PIIMaskingResponseMiddleware."""

    @pytest.mark.asyncio
    async def test_disabled_flag_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flag=OFF → original response без модификации."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", False)

        original_body = b'{"email": "alice@example.com"}'
        app = AsyncMock()
        app.side_effect = _downstream_json(original_body)
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/users"),
            _make_receive(),
            send,
        )

        # Оригинальный body не модифицирован.
        body = _body_message(send)
        assert body["body"] == original_body

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Non-HTTP scope (websocket) → no PII masking."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_path_does_not_match_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Flag=ON но path не matches patterns → no masking."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        original_body = b'{"email": "alice@example.com"}'
        app = AsyncMock()
        app.side_effect = _downstream_json(original_body)
        mw = PIIMaskingResponseMiddleware(
            app=app, path_patterns=[r"^/api/users(/.*)?$"]
        )

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/healthz"),  # not matching
            _make_receive(),
            send,
        )

        # Оригинальный body не модифицирован.
        body = _body_message(send)
        assert body["body"] == original_body

    @pytest.mark.asyncio
    async def test_email_masked_on_json_response(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON response → email маскируется."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        original_body = b'{"email": "alice@example.com", "name": "Alice"}'
        app = AsyncMock()
        app.side_effect = _downstream_json(original_body)
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/users"),
            _make_receive(),
            send,
        )

        # Body МАСКИРОВАН.
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["email"] == "***"
        assert parsed["name"] == "Alice"  # non-PII сохраняется

    @pytest.mark.asyncio
    async def test_non_json_content_type_passes_through(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """text/plain → no masking (только application/json)."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        # Downstream возвращает text/plain.
        async def downstream(scope, receive, send):
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            await send({"type": "http.response.body", "body": b"contact: alice@example.com"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/users"),
            _make_receive(),
            send,
        )

        # text/plain не модифицирован.
        body = _body_message(send)
        assert body["body"] == b"contact: alice@example.com"

    @pytest.mark.asyncio
    async def test_content_length_updated_after_masking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Content-Length header обновляется после masking."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        # Cycle 54 note: orjson re-encodes without spaces → 15 bytes
        # (NOT 16 from the human-readable form b'{"email": "***"}').
        app = AsyncMock()
        app.side_effect = _downstream_json(b'{"email": "alice@example.com"}')
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/users"),
            _make_receive(),
            send,
        )

        # Start message содержит обновлённый Content-Length.
        start = _start_message(send)
        headers = dict(start["headers"])
        # Masked body = b'{"email":"***"}' (15 bytes, no spaces).
        body = _body_message(send)
        assert headers[b"content-length"] == str(len(body["body"])).encode("latin-1")

    @pytest.mark.asyncio
    async def test_does_not_call_downstream_after_masking(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Cycle 54 invariant: после masking downstream НЕ вызывается повторно."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        # Downstream счётчик вызовов.
        call_count = 0

        async def downstream(scope, receive, send):
            nonlocal call_count
            call_count += 1
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": b'{"email": "a@b.com"}'})

        app = AsyncMock()
        app.side_effect = downstream
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/users"),
            _make_receive(),
            send,
        )

        # Downstream вызван ОДИН раз.
        assert call_count == 1
        # PII masked.
        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert parsed["email"] == "***"

    @pytest.mark.asyncio
    async def test_top_level_json_array_masked(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Top-level JSON array → все items рекурсивно маскируются."""
        from src.backend.core.config.features import feature_flags

        monkeypatch.setattr(feature_flags, "pii_response_middleware_enabled", True)

        original_body = (
            b'[{"id": 1, "email": "a@b.com"}, {"id": 2, "email": "c@d.com"}]'
        )
        app = AsyncMock()
        app.side_effect = _downstream_json(original_body)
        mw = PIIMaskingResponseMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/items"),
            _make_receive(),
            send,
        )

        body = _body_message(send)
        parsed = json.loads(body["body"].decode("utf-8"))
        assert isinstance(parsed, list)
        assert all(item["email"] == "***" for item in parsed)
