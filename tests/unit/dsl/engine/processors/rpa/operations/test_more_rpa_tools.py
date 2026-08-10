"""Tests for additional RPA DSL processors (S171 M6.1 — gap fill round 2).

5 new processors:
1. CsvReadProcessor — csv read
2. CsvWriteProcessor — csv write
3. EmailReadProcessor — IMAP read
4. FtpUploadProcessor — SFTP/FTP file upload
5. HttpRequestProcessor — async HTTP request
"""
from __future__ import annotations

import ssl
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestCsvReadProcessor:
    @pytest.mark.asyncio
    async def test_reads_csv_file(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor import (
            CsvReadProcessor,
        )
        csv_file = tmp_path / "data.csv"
        csv_file.write_text("name,age\nAlice,30\nBob,25\n")
        p = CsvReadProcessor(src=str(csv_file), delimiter=",", to="body.rows")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        p.auth_check = AsyncMock(return_value=True)
        await p.process(ex, MagicMock())
        rows = ex.in_message.body.get("rows", [])
        assert len(rows) == 2
        assert rows[0]["name"] == "Alice"

    @pytest.mark.asyncio
    async def test_reads_csv_string(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor import (
            CsvReadProcessor,
        )
        p = CsvReadProcessor(content="a,b\n1,2\n", to="body.rows")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        p.auth_check = AsyncMock(return_value=True)
        await p.process(ex, MagicMock())
        rows = ex.in_message.body.get("rows", [])
        assert rows[0]["a"] == "1"


class TestCsvWriteProcessor:
    @pytest.mark.asyncio
    async def test_writes_csv_file(self, tmp_path: Path) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.csvwriteprocessor import (
            CsvWriteProcessor,
        )
        out = tmp_path / "out.csv"
        p = CsvWriteProcessor(
            dst=str(out), rows=[{"a": "1", "b": "2"}, {"a": "3", "b": "4"}],
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        p.auth_check = AsyncMock(return_value=True)
        await p.process(ex, MagicMock())
        assert out.exists()
        content = out.read_text()
        assert "a,b" in content
        assert "1,2" in content


class TestEmailReadProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import EmailReadProcessor

        p = EmailReadProcessor(
            host="imap.example.com", port=993,
            user="u", password="p", folder="INBOX",
        )
        assert p.host == "imap.example.com"
        assert p.port == 993
        assert p.folder == "INBOX"

    @pytest.mark.asyncio
    async def test_reads_via_imap(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import EmailReadProcessor

        p = EmailReadProcessor(
            host="imap.example.com", port=993,
            user="u", password="p", folder="INBOX",
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        p.auth_check = AsyncMock(return_value=True)
        with patch("imaplib.IMAP4_SSL") as mock_imap:
            mock_conn = MagicMock()
            mock_conn.list.return_value = ("OK", [b'(\\HasNoChildren) "/" "INBOX"'])
            mock_conn.select.return_value = ("OK", [b"1"])
            mock_conn.search.return_value = ("OK", [b"1"])
            mock_conn.fetch.return_value = (
                "OK",
                [(b"1 (RFC822 {100}", b"From: a@b\r\nSubject: t\r\n\r\nbody")],
            )
            mock_conn.logout.return_value = ("OK", None)
            mock_imap.return_value = mock_conn
            await p.process(ex, MagicMock())
        assert "emails" in ex.in_message.body


class TestFtpUploadProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
            FtpUploadProcessor,
        )
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path="/tmp/file.txt", remote_path="/upload/file.txt",
        )
        assert p.host == "ftp.example.com"
        assert p.port == 21
        # Default: strict TLS, no insecure flag set.
        assert p._allow_insecure is False

    def test_insecure_requires_both_flag_and_env(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
            FtpUploadProcessor,
        )

        # Flag without env → still secure.
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path="/tmp/file.txt", remote_path="/r",
            allow_insecure_ftp=True,
        )
        assert p._allow_insecure is False

        # Env without flag → still secure.
        monkeypatch.setenv("FTP_INSECURE_OK", "1")
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path="/tmp/file.txt", remote_path="/r",
        )
        assert p._allow_insecure is False

        # Both → insecure allowed.
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path="/tmp/file.txt", remote_path="/r",
            allow_insecure_ftp=True,
        )
        assert p._allow_insecure is True

    @pytest.mark.asyncio
    async def test_plaintext_ftplib_never_imported_by_default(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Default path must not instantiate ``ftplib.FTP`` — only ``FTP_TLS``."""
        from src.backend.dsl.engine.processors.rpa.operations import (
            ftpuploadprocessor as ftp_mod,
        )
        from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
            FtpUploadProcessor,
        )

        src = tmp_path / "data.txt"
        src.write_text("hello")
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path=str(src), remote_path="/r/x.txt",
        )

        plain_calls: list[Any] = []
        tls_calls: list[Any] = []

        class _StubFTP:
            def __init__(self, *a: Any, **kw: Any) -> None:
                if "context" in kw:
                    tls_calls.append((a, kw))
                else:
                    plain_calls.append((a, kw))

            def connect(self, *a: Any, **kw: Any) -> None: ...
            def login(self, *a: Any, **kw: Any) -> None: ...
            def prot_p(self) -> None: ...
            def storbinary(self, *a: Any, **kw: Any) -> None: ...
            def quit(self) -> None: ...
            def close(self) -> None: ...

        # Patch the names imported inside ``_upload`` (lazy import).
        fake_module = type(
            "FakeFtpLib",
            (),
            {"FTP": _StubFTP, "FTP_TLS": _StubFTP},
        )
        monkeypatch.setattr(ftp_mod, "ftplib", fake_module, raising=False)
        # Also intercept the in-function ``from ftplib import FTP_TLS``.
        import ftplib as real_ftplib

        real_ftplib.FTP_TLS = _StubFTP  # type: ignore[attr-defined]
        real_ftplib.FTP = _StubFTP  # type: ignore[attr-defined]

        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        # auth_check lives on the processor (``self.auth_check``), not the exchange.
        p.auth_check = AsyncMock(return_value=True)
        await p.process(ex, MagicMock())

        assert plain_calls == [], "plaintext ftplib.FTP must not be used"
        assert tls_calls, "FTP_TLS with ssl context must be used"
        ctx = tls_calls[0][1]["context"]
        # CERT_REQUIRED + check_hostname are the security floor.
        assert ctx.verify_mode == ssl.CERT_REQUIRED
        assert ctx.check_hostname is True

    @pytest.mark.asyncio
    async def test_insecure_path_uses_plaintext_with_double_consent(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
    ) -> None:
        """Only when BOTH the ctor flag and env var are set may plaintext be used."""
        from src.backend.dsl.engine.processors.rpa.operations import (
            ftpuploadprocessor as ftp_mod,
        )
        from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
            FtpUploadProcessor,
        )

        monkeypatch.setenv("FTP_INSECURE_OK", "1")
        src = tmp_path / "data.txt"
        src.write_text("hello")
        p = FtpUploadProcessor(
            host="ftp.example.com", port=21,
            user="u", password="p",
            local_path=str(src), remote_path="/r/x.txt",
            allow_insecure_ftp=True,
        )
        assert p._allow_insecure is True

        plain_calls: list[Any] = []
        tls_calls: list[Any] = []

        class _StubFTP:
            def __init__(self, *a: Any, **kw: Any) -> None:
                if "context" in kw:
                    tls_calls.append((a, kw))
                else:
                    plain_calls.append((a, kw))

            def connect(self, *a: Any, **kw: Any) -> None: ...
            def login(self, *a: Any, **kw: Any) -> None: ...
            def prot_p(self) -> None: ...
            def storbinary(self, *a: Any, **kw: Any) -> None: ...
            def quit(self) -> None: ...
            def close(self) -> None: ...

        import ftplib as real_ftplib

        real_ftplib.FTP = _StubFTP  # type: ignore[attr-defined]
        real_ftplib.FTP_TLS = _StubFTP  # type: ignore[attr-defined]
        monkeypatch.setattr(ftp_mod, "ftplib", real_ftplib, raising=False)

        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        # auth_check lives on the processor (``self.auth_check``), not the exchange.
        p.auth_check = AsyncMock(return_value=True)
        await p.process(ex, MagicMock())

        assert plain_calls, "explicit-insecure path must use plain FTP"
        assert tls_calls == []


class TestHttpRequestProcessor:
    @pytest.mark.asyncio
    async def test_get_request(self) -> None:
        from src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor import (
            HttpRequestProcessor,
        )
        p = HttpRequestProcessor(method="GET", url="https://api.example.com/data")
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        p.auth_check = AsyncMock(return_value=True)
        # Mock the capability-checked HTTP client factory used by the processor.
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.json = MagicMock(return_value={"ok": True})
        mock_resp.text = '{"ok": true}'

        class _MockClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False
            async def request(self, *a, **kw):
                return mock_resp

        with patch(
            "src.backend.core.net.migration_helper.make_http_client",
            return_value=_MockClient(),
        ):
            await p.process(ex, MagicMock())

        assert ex.set_property.called
        call_args = ex.set_property.call_args_list[-1]
        target, value = call_args[0]
        assert target == "body"
        assert value["status"] == 200
        assert value["data"] == {"ok": True}
