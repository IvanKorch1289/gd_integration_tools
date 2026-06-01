# ruff: noqa: S101
"""Тесты mTLS-поддержки в :class:`HttpxClient` (Wave 1.3 / S2)."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.clients.transport.http_httpx import HttpxClient


class _StubSettings:
    """Мок-настройки HttpBaseSettings (только нужные mTLS поля + минимум)."""

    def __init__(
        self,
        *,
        client_cert_path: Path | None = None,
        client_key_path: Path | None = None,
        client_cert_password: Any | None = None,
    ) -> None:
        self.limit = 100
        self.limit_per_host = 10
        self.keepalive_timeout = 30
        self.connect_timeout = 5
        self.sock_read_timeout = 30
        self.total_timeout = 60
        self.ssl_verify = True
        self.client_cert_path = client_cert_path
        self.client_key_path = client_key_path
        self.client_cert_password = client_cert_password


@pytest.mark.asyncio
async def test_no_cert_does_not_pass_cert_kwarg() -> None:
    """Без cert paths — kwarg ``cert`` не пробрасывается (backward-compat)."""
    client = HttpxClient()
    client._http_settings = _StubSettings()  # type: ignore[assignment]
    with patch(
        "src.backend.infrastructure.clients.transport.http_httpx.httpx.AsyncClient"
    ) as mock_ac:
        await client._ensure_client()
    assert mock_ac.called
    kwargs = mock_ac.call_args.kwargs
    assert "cert" not in kwargs


@pytest.mark.asyncio
async def test_cert_paths_passed_as_tuple() -> None:
    """С обоими ``*_path`` — ``cert`` приходит как ``(cert, key)``."""
    cert_p = Path("/etc/ssl/client.crt")
    key_p = Path("/etc/ssl/client.key")
    client = HttpxClient()
    client._http_settings = _StubSettings(  # type: ignore[assignment]
        client_cert_path=cert_p, client_key_path=key_p
    )
    with patch(
        "src.backend.infrastructure.clients.transport.http_httpx.httpx.AsyncClient"
    ) as mock_ac:
        await client._ensure_client()
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["cert"] == (str(cert_p), str(key_p))


@pytest.mark.asyncio
async def test_cert_paths_with_password_triple() -> None:
    """С password — ``cert`` приходит как ``(cert, key, password)``."""

    class _FakeSecret:
        def __init__(self, v: str) -> None:
            self._v = v

        def get_secret_value(self) -> str:
            return self._v

    client = HttpxClient()
    client._http_settings = _StubSettings(  # type: ignore[assignment]
        client_cert_path=Path("/c.crt"),
        client_key_path=Path("/k.key"),
        client_cert_password=_FakeSecret("pwd123"),
    )
    with patch(
        "src.backend.infrastructure.clients.transport.http_httpx.httpx.AsyncClient"
    ) as mock_ac:
        await client._ensure_client()
    kwargs = mock_ac.call_args.kwargs
    assert kwargs["cert"] == ("/c.crt", "/k.key", "pwd123")


@pytest.mark.asyncio
async def test_cert_only_one_path_no_op() -> None:
    """Один из ``*_path`` пуст — ``cert`` не передаётся (валидация config-time)."""
    client = HttpxClient()
    client._http_settings = _StubSettings(  # type: ignore[assignment]
        client_cert_path=Path("/c.crt"), client_key_path=None
    )
    with patch(
        "src.backend.infrastructure.clients.transport.http_httpx.httpx.AsyncClient"
    ) as mock_ac:
        await client._ensure_client()
    assert "cert" not in mock_ac.call_args.kwargs


@pytest.mark.asyncio
async def test_cert_rotation_resets_client() -> None:
    """Callback ротации сбрасывает self._client (next ensure пересоздаст)."""
    client = HttpxClient()
    client._http_settings = _StubSettings(  # type: ignore[assignment]
        client_cert_path=Path("/c.crt"), client_key_path=Path("/k.key")
    )
    fake_old_client = MagicMock()
    fake_old_client.is_closed = False

    async def _fake_aclose() -> None:
        fake_old_client.aclose_called = True

    fake_old_client.aclose = _fake_aclose
    client._client = fake_old_client
    client._on_cert_rotated()
    assert client._client is None
