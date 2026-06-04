"""Unit tests for rate-limit identifier/callback helpers."""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException, Request, status

from src.backend.core.decorators.limiting_callbacks import (
    default_callback,
    default_identifier,
)


@pytest.mark.asyncio
async def test_default_identifier_with_user() -> None:
    req = MagicMock(spec=Request)
    req.user = MagicMock()
    req.user.id = "42"
    req.headers = {}
    req.url.path = "/api"
    result = await default_identifier(req)
    assert result == "user:42"


@pytest.mark.asyncio
async def test_default_identifier_with_forwarded_for() -> None:
    req = MagicMock(spec=Request)
    req.user = None
    req.headers = {"x-forwarded-for": "1.2.3.4, 5.6.7.8"}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    req.url.path = "/api"
    result = await default_identifier(req)
    assert result == "ip:1.2.3.4:/api"


@pytest.mark.asyncio
async def test_default_identifier_fallback_ip() -> None:
    req = MagicMock(spec=Request)
    req.user = None
    req.headers = {}
    req.client = MagicMock()
    req.client.host = "10.0.0.1"
    req.url.path = "/test"
    result = await default_identifier(req)
    assert result == "ip:10.0.0.1:/test"


@pytest.mark.asyncio
async def test_default_identifier_no_client() -> None:
    req = MagicMock(spec=Request)
    req.user = None
    req.headers = {}
    req.client = None
    req.url.path = "/"
    result = await default_identifier(req)
    assert result == "ip:unknown:/"


@pytest.mark.asyncio
async def test_default_callback_raises_429() -> None:
    req = MagicMock(spec=Request)
    resp = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await default_callback(req, resp, 5500)
    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert exc_info.value.headers["Retry-After"] == "5"
