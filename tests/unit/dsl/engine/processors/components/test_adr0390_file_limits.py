"""ADR-0390 (волна 18, кластер G1) — лимиты файловых/http-процессоров.

Дефект (9) [medium/low]: процессоры читали/отдавали данные без ограничения
объёма:

* ``FileReadProcessor`` — файл целиком в памяти exchange'а;
* ``ExcelReadProcessor`` — все строки листа в памяти;
* ``HttpRequestProcessor`` — тело ответа целиком в памяти.

Фикс: понятные лимиты + понятная ошибка (без новых config-ключей — лимиты
живут в модулях, ADR-0362).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.processors.components import filereadprocessor


def _exchange(body: Any = None) -> MagicMock:
    ex = MagicMock()
    ex.in_message = MagicMock()
    ex.in_message.body = {} if body is None else body
    ex.properties = {}
    ex.set_property = MagicMock()
    ex.set_error = MagicMock()
    ex.stop = MagicMock()
    ex.fail = MagicMock()
    return ex


@pytest.mark.asyncio
async def test_file_read_rejects_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(9) FileRead: файл больше лимита → понятная ошибка, файл не читается."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    monkeypatch.setattr(filereadprocessor, "_MAX_FILE_READ_BYTES", 8)
    src = tmp_path / "big.txt"
    src.write_text("x" * 100)

    from src.backend.dsl.engine.processors.components.filereadprocessor import (
        FileReadProcessor,
    )

    proc = FileReadProcessor(path=str(src))
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "exceeds" in ex.fail.call_args[0][0]
    ex.set_out.assert_not_called()


@pytest.mark.asyncio
async def test_file_read_reads_small_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Сан-санк: небольшой файл читается как раньше."""
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))
    src = tmp_path / "small.txt"
    src.write_text("hello")

    from src.backend.dsl.engine.processors.components.filereadprocessor import (
        FileReadProcessor,
    )

    proc = FileReadProcessor(path=str(src))
    ex = _exchange()

    await proc.process(ex, MagicMock())

    ex.fail.assert_not_called()
    ex.set_out.assert_called_once()


@pytest.mark.asyncio
async def test_excel_read_rejects_too_many_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """(9) ExcelRead: больше лимита строк → понятная ошибка."""
    pytest.importorskip("openpyxl")
    from openpyxl import Workbook

    from src.backend.dsl.engine.processors.rpa import documents

    monkeypatch.setattr(documents, "_MAX_EXCEL_ROWS", 2)
    monkeypatch.setenv("DSL_ALLOWED_PATHS", str(tmp_path))

    wb = Workbook()
    ws = wb.active
    ws.append(["a", "b"])
    for i in range(5):
        ws.append([i, i])
    path = tmp_path / "book.xlsx"
    wb.save(path)

    from src.backend.dsl.engine.processors.rpa.documents import ExcelReadProcessor

    proc = ExcelReadProcessor()
    proc.auth_check = AsyncMock(return_value=True)
    ex = _exchange(str(path))

    await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "больше 2 строк" in ex.fail.call_args[0][0]


@pytest.mark.asyncio
async def test_http_request_rejects_oversized_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(9) HttpRequest: ответ больше лимита → понятная ошибка."""
    from src.backend.dsl.engine.processors.rpa.operations import httprequestprocessor

    monkeypatch.setattr(httprequestprocessor, "_MAX_HTTP_RESPONSE_BYTES", 10)

    from src.backend.dsl.engine.processors.rpa.operations.httprequestprocessor import (
        HttpRequestProcessor,
    )

    proc = HttpRequestProcessor(method="GET", url="https://example.com/data")
    proc.auth_check = AsyncMock(return_value=True)
    ex = _exchange()

    class _Resp:
        status_code = 200
        headers = {"content-type": "application/json"}
        content = b"x" * 100
        text = "x" * 100

        def json(self) -> Any:
            return {"ok": True}

    class _Client:
        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *a: Any) -> bool:
            return False

        async def request(self, *a: Any, **kw: Any) -> _Resp:
            return _Resp()

    from unittest.mock import patch

    with patch(
        "src.backend.core.net.migration_helper.make_http_client", return_value=_Client()
    ):
        await proc.process(ex, MagicMock())

    ex.fail.assert_called_once()
    assert "exceeds" in ex.fail.call_args[0][0]
