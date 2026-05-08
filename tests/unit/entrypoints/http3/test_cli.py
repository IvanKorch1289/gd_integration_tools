"""Тесты CLI integration ``run_from_settings``.

Проверяют граничные условия: запуск без extra ``http3``, без cert/key,
с выключенным ``http3_enabled``. Реальный event-loop не запускается.
"""

# ruff: noqa: S101

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.backend.entrypoints.http3.cli import run_from_settings


def _stub_settings(**overrides) -> SimpleNamespace:
    base = {
        "host": "127.0.0.1",
        "http3_enabled": True,
        "http3_port": 8443,
        "http3_certfile": "cert.pem",
        "http3_keyfile": "key.pem",
        "http3_max_datagram_frame_size": 65536,
        "http3_idle_timeout": 60.0,
    }
    base.update(overrides)
    return SimpleNamespace(app=SimpleNamespace(**base))


def test_run_rejects_when_disabled(tmp_path: Path) -> None:
    settings = _stub_settings(http3_enabled=False)
    with patch("src.backend.core.config.settings.settings", settings):
        with pytest.raises(RuntimeError, match="APP_HTTP3_ENABLED"):
            run_from_settings()


def test_run_rejects_without_cert(tmp_path: Path) -> None:
    settings = _stub_settings(http3_certfile=None)
    with patch("src.backend.core.config.settings.settings", settings):
        with pytest.raises(RuntimeError, match="APP_HTTP3_CERTFILE"):
            run_from_settings()


def test_run_rejects_without_key(tmp_path: Path) -> None:
    settings = _stub_settings(http3_keyfile=None)
    with patch("src.backend.core.config.settings.settings", settings):
        with pytest.raises(RuntimeError, match="APP_HTTP3_KEYFILE"):
            run_from_settings()


def test_run_rejects_when_aioquic_missing(tmp_path: Path) -> None:
    """Без extra ``http3`` — RuntimeError со ссылкой на uv sync."""
    cert = tmp_path / "cert.pem"
    cert.write_bytes(b"-----BEGIN CERTIFICATE-----\n")
    key = tmp_path / "key.pem"
    key.write_bytes(b"-----BEGIN PRIVATE KEY-----\n")
    settings = _stub_settings(http3_certfile=str(cert), http3_keyfile=str(key))

    with patch("src.backend.core.config.settings.settings", settings):
        with patch(
            "src.backend.entrypoints.http3.cli._ensure_aioquic_installed",
            side_effect=RuntimeError("uv sync --extra http3"),
        ):
            with pytest.raises(RuntimeError, match="extra http3"):
                run_from_settings()
