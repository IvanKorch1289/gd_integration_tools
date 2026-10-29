"""ADR-0390 (волна 18, кластер G1) — FTP plaintext-гейт.

Дефект (4) [high]: ``FtpUploadProcessor`` определял production по
deprecated ``APP_ENV`` — при каноническом ``APP_ENVIRONMENT=production``
(или YAML-профиле ``prod``) гейт fail-open'ил: ``FTP_INSECURE_OK=1`` +
``allow_insecure_ftp=True`` включали plaintext-FTP, и пароль/содержимое
файла уходили по сети открытым текстом.

Теперь источник окружения — ``settings.app.environment``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
    _INSECURE_ENV,
    FtpUploadProcessor,
)


def _prod_settings() -> Any:
    class _Settings:
        class app:
            environment = "production"

    return _Settings()


def _dev_settings() -> Any:
    class _Settings:
        class app:
            environment = "development"

    return _Settings()


def test_plaintext_disabled_in_production(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """(4) production → plaintext-режим выключен даже при обоих флагах."""
    monkeypatch.setenv(_INSECURE_ENV, "1")
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _prod_settings(), raising=False
    )

    proc = FtpUploadProcessor(
        host="example.com",
        user="u",
        password="p",
        local_path=str(tmp_path / "f.txt"),
        remote_path="/r.txt",
        allow_insecure_ftp=True,
    )

    assert proc._allow_insecure is False


def test_plaintext_disabled_when_environment_unknown(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """(4) Fail-closed: окружение определить не удалось → plaintext выключен."""
    monkeypatch.setenv(_INSECURE_ENV, "1")
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", object(), raising=False
    )

    proc = FtpUploadProcessor(
        host="example.com",
        user="u",
        password="p",
        local_path=str(tmp_path / "f.txt"),
        remote_path="/r.txt",
        allow_insecure_ftp=True,
    )

    assert proc._allow_insecure is False


def test_plaintext_enabled_in_development_with_both_flags(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Сан-санк: в development legacy-режим по-прежнему доступен."""
    monkeypatch.setenv(_INSECURE_ENV, "1")
    monkeypatch.setattr(
        "src.backend.core.config.settings.settings", _dev_settings(), raising=False
    )

    proc = FtpUploadProcessor(
        host="example.com",
        user="u",
        password="p",
        local_path=str(tmp_path / "f.txt"),
        remote_path="/r.txt",
        allow_insecure_ftp=True,
    )

    assert proc._allow_insecure is True
