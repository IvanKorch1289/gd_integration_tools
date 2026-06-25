"""Tests for additional RPA DSL processors (S171 M6.1 — gap fill round 2).

5 new processors:
1. CsvReadProcessor — csv read
2. CsvWriteProcessor — csv write
3. EmailReadProcessor — IMAP read
4. FtpUploadProcessor — SFTP/FTP file upload
5. HttpRequestProcessor — async HTTP request
"""
from __future__ import annotations
import asyncio
from pathlib import Path
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
            dst=str(out), rows=[{"a": "1", "b": "2"}, {"a": "3", "b": "4"}]
        )
        ex = MagicMock()
        ex.in_message = MagicMock()
        ex.in_message.body = {}
        ex.set_property = MagicMock()
        ex.set_error = MagicMock()
        ex.stop = MagicMock()
        await p.process(ex, MagicMock())
        assert out.exists()
        content = out.read_text()
        assert "a,b" in content
        assert "1,2" in content


class TestEmailReadProcessor:
    def test_instantiates(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import (
            EmailReadProcessor,
        )
        p = EmailReadProcessor(
            host="imap.example.com", port=993,
            user="u", password="p", folder="INBOX",
        )
        assert p.host == "imap.example.com"
        assert p.port == 993
        assert p.folder == "INBOX"

    @pytest.mark.asyncio
    async def test_reads_via_imap(self) -> None:
        from src.backend.dsl.engine.processors.rpa.system import (
            EmailReadProcessor,
        )
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
        # Mock via module-level: aiohttp is imported in process()
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.headers = {"content-type": "application/json"}
        mock_resp.text = AsyncMock(return_value='{"ok": true}')

        class _MockRequest:
            async def __aenter__(s):
                return mock_resp
            async def __aexit__(s, *a):
                return False

        class _MockSession:
            def request(self, *a, **kw):
                return _MockRequest()
            async def __aenter__(self):
                return self
            async def __aexit__(self, *a):
                return False

        from src.backend.dsl.engine.processors.rpa.operations import httprequestprocessor as hr_mod
        with patch.object(hr_mod, "aiohttp") as mock_aiohttp:
            mock_aiohttp.ClientSession.return_value = _MockSession()
            mock_aiohttp.ClientTimeout = MagicMock()
            await p.process(ex, MagicMock())

        # Result written via set_property (BaseProcessor helper)
        assert ex.set_property.called
        call_args = ex.set_property.call_args_list[-1]
        # call('body', {'status': ..., 'headers': ..., 'data': ...})
        target, value = call_args[0]
        assert target == "body"
        assert value["status"] == 200
        assert value["data"] == {"ok": True}
