"""Unit-тесты для ``_resolve_known_hosts`` (Sprint 17 W1 b2 partial closure).

Покрывают V1 security constraint: SFTP-клиент должен требовать явный путь
к ``known_hosts`` в production-профилях и допускать skip только в
``dev_light``.
"""

from __future__ import annotations

import importlib

import pytest

from src.backend.core.config.profile import APP_PROFILE_ENV


def _reload_sftp_module():
    """Перезагружает модуль ``sftp`` после изменения settings/env.

    Settings-singleton кэширует ``transport_settings`` на момент импорта,
    поэтому для проверки изменения ``TRANSPORT_SFTP_KNOWN_HOSTS_PATH``
    нужен повторный импорт модуля.
    """
    import src.backend.core.config.settings as settings_module
    import src.backend.core.config.transport as transport_module
    import src.backend.infrastructure.clients.transport.sftp as sftp_module

    importlib.reload(transport_module)
    importlib.reload(settings_module)
    importlib.reload(sftp_module)
    return sftp_module


def test_resolve_known_hosts_dev_light_without_path_returns_empty_tuple(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В dev_light без пути _resolve_known_hosts() возвращает () (skip)."""
    monkeypatch.setenv(APP_PROFILE_ENV, "dev_light")
    monkeypatch.delenv("TRANSPORT_SFTP_KNOWN_HOSTS_PATH", raising=False)
    sftp_module = _reload_sftp_module()

    result = sftp_module._resolve_known_hosts()

    assert result == ()


def test_resolve_known_hosts_prod_without_path_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В prod без пути _resolve_known_hosts() поднимает ValueError (V1)."""
    monkeypatch.setenv(APP_PROFILE_ENV, "prod")
    monkeypatch.delenv("TRANSPORT_SFTP_KNOWN_HOSTS_PATH", raising=False)
    sftp_module = _reload_sftp_module()

    with pytest.raises(ValueError, match="TRANSPORT_SFTP_KNOWN_HOSTS_PATH"):
        sftp_module._resolve_known_hosts()


def test_resolve_known_hosts_returns_path_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """Если путь задан — _resolve_known_hosts() возвращает его строкой."""
    known_hosts_file = tmp_path / "known_hosts"
    known_hosts_file.write_text("example.com ssh-rsa AAAA...")
    monkeypatch.setenv(APP_PROFILE_ENV, "prod")
    monkeypatch.setenv("TRANSPORT_SFTP_KNOWN_HOSTS_PATH", str(known_hosts_file))
    sftp_module = _reload_sftp_module()

    result = sftp_module._resolve_known_hosts()

    assert result == str(known_hosts_file)


def test_resolve_known_hosts_dev_profile_without_path_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В dev (не dev_light) без пути требуется явная декларация."""
    monkeypatch.setenv(APP_PROFILE_ENV, "dev")
    monkeypatch.delenv("TRANSPORT_SFTP_KNOWN_HOSTS_PATH", raising=False)
    sftp_module = _reload_sftp_module()

    with pytest.raises(ValueError, match="TRANSPORT_SFTP_KNOWN_HOSTS_PATH"):
        sftp_module._resolve_known_hosts()


def test_ftp_module_imports_after_except_fix() -> None:
    """ftp.py:170 — Python-3 tuple except clause не ломает import."""
    import src.backend.infrastructure.clients.transport.ftp as ftp_module

    assert hasattr(ftp_module, "FTPClient")
    assert hasattr(ftp_module, "get_ftp_client")
