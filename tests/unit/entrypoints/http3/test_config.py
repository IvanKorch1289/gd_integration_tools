"""Тесты Http3ServerConfig — валидация TLS-путей без сетевого запуска."""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path

import pytest

from src.backend.entrypoints.http3.config import Http3ServerConfig


def test_config_requires_existing_certfile(tmp_path: Path) -> None:
    """Отсутствующий cert даёт явный ``FileNotFoundError`` со ссылкой на env."""
    keyfile = tmp_path / "key.pem"
    keyfile.write_bytes(b"-----BEGIN PRIVATE KEY-----\n")
    missing_cert = tmp_path / "missing.pem"

    with pytest.raises(FileNotFoundError, match="APP_HTTP3_CERTFILE"):
        Http3ServerConfig(
            host="127.0.0.1",
            port=8443,
            certfile=missing_cert,
            keyfile=keyfile,
        )


def test_config_requires_existing_keyfile(tmp_path: Path) -> None:
    """Отсутствующий key даёт явный ``FileNotFoundError`` со ссылкой на env."""
    certfile = tmp_path / "cert.pem"
    certfile.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    missing_key = tmp_path / "missing.pem"

    with pytest.raises(FileNotFoundError, match="APP_HTTP3_KEYFILE"):
        Http3ServerConfig(
            host="127.0.0.1",
            port=8443,
            certfile=certfile,
            keyfile=missing_key,
        )


def test_config_defaults(tmp_path: Path) -> None:
    """Defaults: ALPN h3+h3-29, datagram 64KB, idle 60s."""
    cert = tmp_path / "cert.pem"
    cert.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    key = tmp_path / "key.pem"
    key.write_bytes(b"-----BEGIN PRIVATE KEY-----\n")

    config = Http3ServerConfig(
        host="0.0.0.0",  # noqa: S104  # тест-только
        port=8443,
        certfile=cert,
        keyfile=key,
    )
    assert config.alpn_protocols == ("h3", "h3-29")
    assert config.max_datagram_frame_size == 65536
    assert config.idle_timeout == 60.0


def test_config_is_immutable(tmp_path: Path) -> None:
    """``frozen=True`` запрещает мутацию (важно для shared между coroutines)."""
    cert = tmp_path / "cert.pem"
    cert.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    key = tmp_path / "key.pem"
    key.write_bytes(b"-----BEGIN PRIVATE KEY-----\n")

    config = Http3ServerConfig(
        host="127.0.0.1", port=8443, certfile=cert, keyfile=key
    )
    with pytest.raises(AttributeError):
        config.port = 9000  # type: ignore[misc]
