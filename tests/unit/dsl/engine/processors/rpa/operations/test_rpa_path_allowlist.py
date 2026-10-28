"""Wave 13 Q7 (B) — RPA-процессоры под path-allowlist.

``required_capability`` ограничивает *факт вызова* процессора, но не *путь*,
к которому он обращается. Второй независимый барьер — ``validate_path``
(allowlist каталогов). Тесты проверяют, что все четыре RPA-процессора
(FileList / FileWatch / FilteredDirectoryScan / FtpUpload) отказывают
вне allowlist и НЕ читают/сканируют/выгружают данные.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.rpa.operations.csvreadprocessor import (
    CsvReadProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations.csvwriteprocessor import (
    CsvWriteProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations.filelistprocessor import (
    FileListProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations.filewatchprocessor import (
    FileWatchProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations.filtereddirectoryscanprocessor import (
    FilteredDirectoryScanProcessor,
)
from src.backend.dsl.engine.processors.rpa.operations.ftpuploadprocessor import (
    FtpUploadProcessor,
)


def _exchange(body: Any = None) -> Exchange[Any]:
    """Настоящий Exchange — чтобы проверять status/error, а не mock-вызовы."""
    return Exchange(in_message=Message(body={} if body is None else body, headers={}))


def _allow(proc: Any) -> None:
    """Bypass capability-gate: тестируем path-барьер, а не capability."""
    proc.auth_check = AsyncMock(return_value=True)


def _body(ex: Exchange[Any]) -> dict[str, Any]:
    """Тело exchange как dict (может быть None)."""
    body = ex.in_message.body
    return body if isinstance(body, dict) else {}


class TestFileListPathAllowlist:
    """FileListProcessor — glob-паттерн (в т.ч. из тела запроса)."""

    @pytest.mark.asyncio
    async def test_pattern_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        (tmp_path / "a.txt").write_text("a")

        proc = FileListProcessor(pattern=str(tmp_path / "*.txt"), to="body.files")
        _allow(proc)
        ex = _exchange()

        with patch("glob.glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_glob.assert_not_called()
        assert not _body(ex).get("files")

    @pytest.mark.asyncio
    async def test_pattern_from_request_body_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Паттерн из тела запроса — недоверенный ввод."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        (tmp_path / "secret.txt").write_text("secret")

        proc = FileListProcessor(to="body.files")
        _allow(proc)
        ex = _exchange({"pattern": str(tmp_path / "*.txt")})

        with patch("glob.glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        mock_glob.assert_not_called()
        assert not _body(ex).get("files")

    @pytest.mark.asyncio
    async def test_pattern_inside_allowlist_lists_files(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        (allowed / "b.log").write_text("b")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FileListProcessor(pattern=str(allowed / "*.txt"), to="body.files")
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert sorted(Path(f).name for f in _body(ex).get("files", [])) == ["a.txt"]

    @pytest.mark.asyncio
    async def test_relative_pattern_resolved_from_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Пустой статический префикс → резолв от cwd."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.log").write_text("a")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))
        monkeypatch.chdir(allowed)

        proc = FileListProcessor(pattern="*.log", to="body.files")
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert sorted(Path(f).name for f in _body(ex).get("files", [])) == ["a.log"]

    @pytest.mark.asyncio
    async def test_relative_pattern_blocked_when_cwd_outside_allowlist(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        monkeypatch.chdir(tmp_path)

        proc = FileListProcessor(pattern="*.log", to="body.files")
        _allow(proc)
        ex = _exchange()

        with patch("glob.glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        mock_glob.assert_not_called()

    @pytest.mark.asyncio
    async def test_traversal_pattern_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))

        proc = FileListProcessor(
            pattern=str(tmp_path / ".." / ".." / "etc" / "*.conf"), to="body.files"
        )
        _allow(proc)
        ex = _exchange()

        with patch("glob.glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "traversal" in (ex.error or "")
        mock_glob.assert_not_called()

    @pytest.mark.asyncio
    async def test_magic_in_parent_segment_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``/data/uploads*/*.txt`` может матчить ``/data/uploads_backup/``.

        Статический префикс должен быть каталогом, а не «началом имени».
        """
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))

        proc = FileListProcessor(pattern="/data/uploads*/x.txt", to="body.files")
        _allow(proc)
        ex = _exchange()

        with patch("glob.glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        mock_glob.assert_not_called()


class TestFileWatchPathAllowlist:
    """FileWatchProcessor — наблюдаемая директория."""

    @pytest.mark.asyncio
    async def test_directory_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))

        proc = FileWatchProcessor(directory=str(tmp_path), pattern="*.txt", timeout=0.1)
        _allow(proc)
        ex = _exchange()

        with patch("watchdog.observers.Observer") as mock_observer:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_observer.assert_not_called()
        assert "changes" not in _body(ex)

    @pytest.mark.asyncio
    async def test_directory_inside_allowlist_is_watched(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FileWatchProcessor(directory=str(allowed), pattern="*.txt", timeout=0.1)
        _allow(proc)
        ex = _exchange()

        with patch("watchdog.observers.Observer"):
            await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert "changes" in _body(ex)


class TestDirectoryScanPathAllowlist:
    """FilteredDirectoryScanProcessor — сканируемая директория."""

    @pytest.mark.asyncio
    async def test_directory_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        (tmp_path / "secret.txt").write_text("secret")

        proc = FilteredDirectoryScanProcessor(
            directory=str(tmp_path), pattern="*.txt", to="body.files"
        )
        _allow(proc)
        ex = _exchange()

        with patch.object(Path, "glob") as mock_glob:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_glob.assert_not_called()
        assert not _body(ex).get("files")

    @pytest.mark.asyncio
    async def test_directory_inside_allowlist_is_scanned(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        (allowed / "a.txt").write_text("a")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FilteredDirectoryScanProcessor(
            directory=str(allowed), pattern="*.txt", to="body.files"
        )
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert sorted(Path(f).name for f in _body(ex).get("files", [])) == ["a.txt"]


class TestFtpUploadPathAllowlist:
    """FtpUploadProcessor — локальный файл (эксфильтрация через FTP)."""

    @pytest.mark.asyncio
    async def test_local_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        secret = tmp_path / "secret.txt"
        secret.write_text("TOP SECRET")

        proc = FtpUploadProcessor(
            host="ftp.example.com",
            user="u",
            password="p",
            local_path=str(secret),
            remote_path="/r.txt",
        )
        _allow(proc)
        ex = _exchange()

        real_open = open
        opened: list[str] = []

        def _spy_open(file: Any, *args: Any, **kwargs: Any) -> Any:
            opened.append(str(file))
            return real_open(file, *args, **kwargs)

        with (
            patch("builtins.open", _spy_open),
            patch("ftplib.FTP_TLS") as mock_tls,
            patch("ftplib.FTP") as mock_plain,
        ):
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        # Файл не прочитан, FTP-соединение не установлено.
        assert str(secret) not in opened
        mock_tls.assert_not_called()
        mock_plain.assert_not_called()
        assert not _body(ex).get("uploaded")

    @pytest.mark.asyncio
    async def test_local_path_inside_allowlist_is_uploaded(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        src = allowed / "data.txt"
        src.write_text("hello")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = FtpUploadProcessor(
            host="ftp.example.com",
            user="u",
            password="p",
            local_path=str(src),
            remote_path="/r.txt",
        )
        _allow(proc)
        ex = _exchange()

        stored: list[tuple[str, bytes]] = []

        class _FakeFTP_TLS:
            def __init__(self, **kw: Any) -> None:
                pass

            def connect(self, host: str, port: int) -> None:
                pass

            def login(self, user: str, password: str) -> None:
                pass

            def prot_p(self) -> None:
                pass

            def storbinary(self, cmd: str, fp: Any) -> None:
                stored.append((cmd, fp.read()))

            def quit(self) -> None:
                pass

        with (
            patch("ftplib.FTP_TLS", _FakeFTP_TLS),
            patch("ssl.create_default_context", MagicMock()),
        ):
            await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert stored == [("STOR /r.txt", b"hello")]
        assert _body(ex).get("uploaded") is True


class TestCsvReadPathAllowlist:
    """CsvReadProcessor — исходный CSV-файл."""

    @pytest.mark.asyncio
    async def test_src_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        secret = tmp_path / "secret.csv"
        secret.write_text("name,ssn\nAlice,123-45-6789\n")

        proc = CsvReadProcessor(src=str(secret), to="body.rows")
        _allow(proc)
        ex = _exchange()

        with patch("aiofiles.open") as mock_open:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_open.assert_not_called()
        assert not _body(ex).get("rows")

    @pytest.mark.asyncio
    async def test_src_inside_allowlist_is_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        src = allowed / "data.csv"
        src.write_text("name,age\nAlice,30\n")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = CsvReadProcessor(src=str(src), to="body.rows")
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert _body(ex).get("rows") == [{"name": "Alice", "age": "30"}]

    @pytest.mark.asyncio
    async def test_traversal_src_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))

        proc = CsvReadProcessor(
            src=str(tmp_path / ".." / ".." / "etc" / "passwd.csv"), to="body.rows"
        )
        _allow(proc)
        ex = _exchange()

        with patch("aiofiles.open") as mock_open:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "traversal" in (ex.error or "")
        mock_open.assert_not_called()


class TestCsvWritePathAllowlist:
    """CsvWriteProcessor — целевой CSV-файл."""

    @pytest.mark.asyncio
    async def test_dst_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        dst = tmp_path / "out.csv"

        proc = CsvWriteProcessor(dst=str(dst), rows=[{"a": "1"}])
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        assert not dst.exists()

    @pytest.mark.asyncio
    async def test_dst_outside_allowlist_is_blocked_for_empty_rows(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Пустой список rows тоже пишет файл — путь должен быть проверен."""
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        dst = tmp_path / "empty.csv"

        proc = CsvWriteProcessor(dst=str(dst), rows=[])
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert not dst.exists()

    @pytest.mark.asyncio
    async def test_dst_inside_allowlist_is_written(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        dst = allowed / "out.csv"
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = CsvWriteProcessor(dst=str(dst), rows=[{"a": "1"}])
        _allow(proc)
        ex = _exchange()

        await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        assert dst.exists()
        assert "a" in dst.read_text()


class TestDocumentProcessorsPathAllowlist:
    """PDF/Word/Excel — путь из тела запроса (недоверенный ввод).

    Bytes-ветки (загрузка файла из памяти) allowlist не требуют —
    файловой системы они не касаются.
    """

    @pytest.mark.asyncio
    async def test_pdf_read_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.documents import PdfReadProcessor

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        secret = tmp_path / "secret.pdf"
        secret.write_bytes(b"%PDF-1.4 PII")

        proc = PdfReadProcessor()
        _allow(proc)
        ex = _exchange(str(secret))

        with patch("src.backend.utilities.pdf_reader.read_pdf") as mock_read:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_read.assert_not_called()

    @pytest.mark.asyncio
    async def test_word_read_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.documents import WordReadProcessor

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        secret = tmp_path / "secret.docx"
        secret.write_bytes(b"PK PII")

        proc = WordReadProcessor()
        _allow(proc)
        ex = _exchange(str(secret))

        with patch("docx.Document") as mock_doc:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_doc.assert_not_called()

    @pytest.mark.asyncio
    async def test_excel_read_path_outside_allowlist_is_blocked(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Эксфильтрация PII: body='/tmp/rpa_secret.xlsx' не должен читаться."""
        from src.backend.dsl.engine.processors.rpa.documents import ExcelReadProcessor

        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path / "allowed"))
        secret = tmp_path / "rpa_secret.xlsx"
        secret.write_bytes(b"PK secret")

        proc = ExcelReadProcessor()
        _allow(proc)
        ex = _exchange(str(secret))

        with patch("openpyxl.load_workbook") as mock_wb:
            await proc.process(ex, MagicMock())

        assert ex.status == ExchangeStatus.failed
        assert "outside allowed" in (ex.error or "")
        mock_wb.assert_not_called()

    @pytest.mark.asyncio
    async def test_excel_read_bytes_body_is_not_path_checked(self) -> None:
        """Bytes-ветка allowlist не требует — файловой системы она не касается."""
        from src.backend.dsl.engine.processors.rpa.documents import ExcelReadProcessor

        proc = ExcelReadProcessor()
        _allow(proc)
        ex = _exchange(b"fake-xlsx")

        with patch("openpyxl.load_workbook") as mock_wb:
            mock_book = MagicMock()
            mock_sheet = MagicMock()
            mock_sheet.iter_rows.return_value = [["col1"], ["v1"]]
            mock_book.active = mock_sheet
            mock_wb.return_value = mock_book
            await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        mock_wb.assert_called_once()

    @pytest.mark.asyncio
    async def test_excel_read_path_inside_allowlist_is_read(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.dsl.engine.processors.rpa.documents import ExcelReadProcessor

        allowed = tmp_path / "allowed"
        allowed.mkdir()
        src = allowed / "book.xlsx"
        src.write_bytes(b"PK data")
        monkeypatch.setenv("DSL_ALLOWED_PATHS", str(allowed))

        proc = ExcelReadProcessor()
        _allow(proc)
        ex = _exchange(str(src))

        with patch("openpyxl.load_workbook") as mock_wb:
            mock_book = MagicMock()
            mock_sheet = MagicMock()
            mock_sheet.iter_rows.return_value = [["col1"], ["v1"]]
            mock_book.active = mock_sheet
            mock_wb.return_value = mock_book
            await proc.process(ex, MagicMock())

        assert ex.status != ExchangeStatus.failed
        assert ex.error is None
        mock_wb.assert_called_once()
