"""Unit tests for DataMaskingMiddleware."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from starlette.requests import Request
from starlette.responses import Response

from src.backend.entrypoints.middlewares.data_masking import (
    _EMAIL_RE,
    _PHONE_RE,
    DataMaskingMiddleware,
)


def _json_response(body: bytes) -> Response:
    """Build a Response with a pre-set body_iterator for middleware tests."""
    resp = Response(content=body, media_type="application/json")

    # Pre-seed the iterator so _capture_body can consume it.
    async def _iter():
        yield body

    resp.body_iterator = _iter()  # type: ignore[attr-defined]
    return resp


class TestDataMaskingMiddleware:
    """Tests for :class:`DataMaskingMiddleware`."""

    @pytest.fixture
    def middleware(self) -> DataMaskingMiddleware:
        return DataMaskingMiddleware(AsyncMock())

    @pytest.mark.asyncio
    async def test_non_json_passes_through(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Non-JSON responses are returned unchanged."""
        response = Response(content="plain text", media_type="text/plain")
        call_next = AsyncMock(return_value=response)
        request = Request({"type": "http", "method": "GET", "url": "http://test/"})

        result = await middleware.dispatch(request, call_next)

        assert result is response
        call_next.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_masks_sensitive_keys(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Sensitive dict keys are masked with ***."""
        body = b'{"password": "secret123", "name": "Alice"}'
        response = _json_response(body)
        call_next = AsyncMock(return_value=response)
        request = Request({"type": "http", "method": "GET", "url": "http://test/"})

        result = await middleware.dispatch(request, call_next)

        assert result is response
        chunks = [chunk async for chunk in result.body_iterator]
        masked = b"".join(chunks)
        assert b'"password":"***"' in masked
        assert b'"name":"Alice"' in masked

    @pytest.mark.asyncio
    async def test_masks_nested_sensitive(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Nested sensitive keys are also masked."""
        body = b'{"user": {"api_key": "abc", "email": "a@b.com"}}'
        response = _json_response(body)
        call_next = AsyncMock(return_value=response)
        request = Request({"type": "http", "method": "GET", "url": "http://test/"})

        result = await middleware.dispatch(request, call_next)

        chunks = [chunk async for chunk in result.body_iterator]
        masked = b"".join(chunks)
        assert b'"api_key":"***"' in masked

    def test_mask_value_dict(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value masks dict keys."""
        data = {"token": "t", "safe": "ok"}
        result = middleware._mask_value(data)
        assert result == {"token": "***", "safe": "ok"}

    def test_mask_value_list(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value recurses into lists."""
        data = [{"password": "p"}, {"name": "n"}]
        result = middleware._mask_value(data)
        assert result == [{"password": "***"}, {"name": "n"}]

    def test_mask_value_string_email(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value masks emails in strings."""
        data = "contact: alice@example.com"
        result = middleware._mask_value(data)
        assert "a***e@example.com" in result

    def test_mask_value_string_phone(self, middleware: DataMaskingMiddleware) -> None:
        """_mask_value masks phones in strings."""
        data = "call +7 (999) 123-45-67"
        result = middleware._mask_value(data)
        assert "79*******67" in result

    def test_mask_bytes_invalid_json_returns_raw(
        self, middleware: DataMaskingMiddleware
    ) -> None:
        """Invalid JSON bytes are returned unchanged."""
        raw = b"not json"
        assert middleware._mask_bytes(raw) == raw

    def test_email_re_matches(self) -> None:
        """_EMAIL_RE matches valid emails."""
        assert _EMAIL_RE.search("user@domain.com")
        assert _EMAIL_RE.search("a.b+c@d.co.uk")

    def test_phone_re_matches(self) -> None:
        """_PHONE_RE matches valid phones."""
        assert _PHONE_RE.search("+7 999 123 45 67")
        assert _PHONE_RE.search("89991234567")
