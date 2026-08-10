"""Tests for :class:`FtpUploadProcessor` (S171 M6.1 — V1 hotfix).

Покрывает:
- **Default = TLS**: ``FTP_TLS`` создаётся с ``ssl.create_default_context``
  (``CERT_REQUIRED`` + ``check_hostname=True``) и ``prot_p()`` вызывается
  на data-channel.
- **Plaintext отказ**: без ``allow_insecure_ftp=True`` И ``FTP_INSECURE_OK=1``
  plaintext ``FTP()`` НЕ создаётся.
- **Backward-compat opt-in**: при обоих включенных флагах открывается
  plaintext ``FTP()`` (для legacy dev/test серверов без FTPS).
"""


from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
    _INSECURE_ENV,
    FtpUploadProcessor,
)


def _exchange() -> Exchange[Any]:
    return Exchange(in_message=Message(body={}, headers={}))


class TestFtpUploadSecurity:
    def test_default_uses_tls_with_cert_verification(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / "f.txt"
        local.write_text("x")
        # Ensure insecure flag is NOT set.
        monkeypatch.delenv(_INSECURE_ENV, raising=False)

        ftp_calls: list[Any] = []
        ftp_tls_calls: list[dict[str, Any]] = []
        prot_p_calls: list[int] = []

        class _FakeFTP_TLS:
            def __init__(self, **kw: Any) -> None:
                ftp_tls_calls.append(kw)
                self._ctx = kw.get("context")
                self.prot_p_called = False
                self._logged_in: tuple[str, str] | None = None
                self._stored: list[tuple[str, Any]] = []

            def connect(self, host: str, port: int) -> None:
                ftp_calls.append((host, port))

            def login(self, user: str, password: str) -> None:
                self._logged_in = (user, password)

            def prot_p(self) -> None:
                prot_p_calls.append(1)
                self.prot_p_called = True

            def storbinary(self, cmd: str, fp: Any) -> None:
                self._stored.append((cmd, fp.read()))

            def quit(self) -> None:
                return None

        class _FakeFtplib:
            FTP_TLS = _FakeFTP_TLS
            FTP = MagicMock()  # Must NOT be called on the TLS path.

        proc = FtpUploadProcessor(
            host="example.com",
            user="u",
            password="p",
            local_path=str(local),
            remote_path="/r.txt",
        )
        ctx = MagicMock()
        with (
            patch("ftplib.FTP_TLS", _FakeFTP_TLS),
            patch("ftplib.FTP", _FakeFtplib.FTP),
            patch(
                "ssl.create_default_context",
                return_value=ctx,
            ),
            patch.object(proc, "auth_check", return_value=True),
        ):
            import asyncio

            asyncio.run(proc.process(_exchange(), MagicMock()))

        # TLS path was taken.
        assert len(ftp_tls_calls) == 1
        assert ftp_tls_calls[0]["context"] is ctx
        # Context was configured with cert-required + hostname checks
        # before ``FTP_TLS`` construction.
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True
        # Data channel was upgraded to TLS (RFC 4217).
        assert prot_p_calls == [1]
        # Plaintext ``FTP()`` was never instantiated.
        _FakeFtplib.FTP.assert_not_called()

    def test_plaintext_rejected_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / "f.txt"
        local.write_text("x")
        monkeypatch.delenv(_INSECURE_ENV, raising=False)

        plaintext_calls = {"ftp_constructed": 0, "tls_constructed": 0}

        class _FakeFTP_TLS:
            def __init__(self, **kw: Any) -> None:
                plaintext_calls["tls_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def prot_p(self) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        class _FakeFTP:
            def __init__(self) -> None:
                plaintext_calls["ftp_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        proc = FtpUploadProcessor(
            host="example.com",
            user="u",
            password="p",
            local_path=str(local),
            remote_path="/r.txt",
        )
        with (
            patch("ftplib.FTP_TLS", _FakeFTP_TLS),
            patch("ftplib.FTP", _FakeFTP),
            patch("ssl.create_default_context", MagicMock()),
            patch.object(proc, "auth_check", return_value=True),
        ):
            import asyncio

            asyncio.run(proc.process(_exchange(), MagicMock()))

        # TLS path is mandatory when insecure flag is off.
        assert plaintext_calls["ftp_constructed"] == 0
        assert plaintext_calls["tls_constructed"] == 1

    def test_plaintext_opt_in_requires_both_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / "f.txt"
        local.write_text("x")
        # Set ONLY the env var; ctor flag stays False.
        monkeypatch.setenv(_INSECURE_ENV, "1")

        plaintext_calls = {"ftp_constructed": 0, "tls_constructed": 0}

        class _FakeFTP_TLS:
            def __init__(self, **kw: Any) -> None:
                plaintext_calls["tls_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def prot_p(self) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        class _FakeFTP:
            def __init__(self) -> None:
                plaintext_calls["ftp_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        proc = FtpUploadProcessor(
            host="example.com",
            user="u",
            password="p",
            local_path=str(local),
            remote_path="/r.txt",
            allow_insecure_ftp=False,
        )
        with (
            patch("ftplib.FTP_TLS", _FakeFTP_TLS),
            patch("ftplib.FTP", _FakeFTP),
            patch("ssl.create_default_context", MagicMock()),
            patch.object(proc, "auth_check", return_value=True),
        ):
            import asyncio

            asyncio.run(proc.process(_exchange(), MagicMock()))

        # env=1 alone is not enough → TLS still mandatory.
        assert plaintext_calls["ftp_constructed"] == 0
        assert plaintext_calls["tls_constructed"] == 1

    def test_plaintext_allowed_with_both_flags(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        local = tmp_path / "f.txt"
        local.write_text("x")
        monkeypatch.setenv(_INSECURE_ENV, "1")

        plaintext_calls = {"ftp_constructed": 0, "tls_constructed": 0}

        class _FakeFTP_TLS:
            def __init__(self, **kw: Any) -> None:
                plaintext_calls["tls_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def prot_p(self) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        class _FakeFTP:
            def __init__(self) -> None:
                plaintext_calls["ftp_constructed"] += 1

            def connect(self, *a: Any, **kw: Any) -> None:
                pass

            def login(self, *a: Any, **kw: Any) -> None:
                pass

            def storbinary(self, *a: Any, **kw: Any) -> None:
                pass

            def quit(self) -> None:
                pass

        proc = FtpUploadProcessor(
            host="example.com",
            user="u",
            password="p",
            local_path=str(local),
            remote_path="/r.txt",
            allow_insecure_ftp=True,
        )
        with (
            patch("ftplib.FTP_TLS", _FakeFTP_TLS),
            patch("ftplib.FTP", _FakeFTP),
            patch("ssl.create_default_context", MagicMock()),
            patch.object(proc, "auth_check", return_value=True),
        ):
            import asyncio

            asyncio.run(proc.process(_exchange(), MagicMock()))

        # Both flags + env → legacy plaintext path is reachable.
        assert plaintext_calls["ftp_constructed"] == 1
        assert plaintext_calls["tls_constructed"] == 0
