"""Regression-тесты для cycle 33 P1A: exception envelope.

Покрывает B-12 fix (cycle 34): non-BaseError → 500 c error_id
(uuid4) в envelope + propagation correlation_id из ASGI scope.

Source: src/backend/entrypoints/middlewares/exception_handler.py
"""

# ruff: noqa: S101

from __future__ import annotations

import json
import re
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.exception_handler import (
    ExceptionHandlerMiddleware,
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


def _make_scope(
    path: str = "/path",
    state: dict | None = None,
) -> dict:
    return {
        "type": "http",
        "method": "GET",
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


class TestExceptionHandlerEnvelopeCycle33:
    """Cycle 33 P1A: non-BaseError → 500 c error_id envelope."""

    @pytest.mark.asyncio
    async def test_non_base_error_returns_500_with_error_id_envelope(self) -> None:
        """non-BaseError → 500 c error_id (uuid4) в envelope."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = downstream
        middleware = ExceptionHandlerMiddleware(app)

        send = AsyncMock()
        await middleware(
            _make_scope("/api/v1/foo"),
            _make_receive(),
            send,
        )

        start = _start_message(send)
        assert start is not None
        assert start["status"] == 500

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))

        # Новый envelope (B-12 fix, cycle 34).
        assert parsed["code"] == "internal_error"
        assert parsed["detail"] == "Internal server error"
        # error_id — валидный uuid4 hex (version 4).
        assert re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            parsed["error_id"],
        ), f"error_id не похож на uuid4: {parsed['error_id']!r}"

    @pytest.mark.asyncio
    async def test_correlation_id_propagated_from_scope(self) -> None:
        """correlation_id из scope.state попадает в envelope."""
        app = AsyncMock()

        async def downstream(scope, receive, send):
            raise RuntimeError("boom")

        app.side_effect = downstream
        middleware = ExceptionHandlerMiddleware(app)

        send = AsyncMock()
        await middleware(
            _make_scope(
                "/api/v1/bar",
                state={"correlation_id": "corr-xyz-123", "request_id": "req-abc-456"},
            ),
            _make_receive(),
            send,
        )

        body = _body_message(send)
        assert body is not None
        parsed = json.loads(body["body"].decode("utf-8"))

        assert parsed["correlation_id"] == "corr-xyz-123"
        assert parsed["request_id"] == "req-abc-456"
        # error_id тоже присутствует в envelope.
        assert "error_id" in parsed
