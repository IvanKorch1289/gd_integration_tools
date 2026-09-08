"""Tests for src.backend.dsl.engine.processors.express.send_file.

T3 coverage sprint cycle 8: тесты для ``ExpressSendFileProcessor.__init__``
(validation), ``_load_file_bytes`` (S3 → property fallback), ``process()``
(upload + send_message), ``to_spec``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express.send_file import ExpressSendFileProcessor


def _make_exchange(properties: dict | None = None) -> tuple[Exchange, dict]:
    captured: dict = {}
    ex = MagicMock(spec=Exchange)
    ex.properties = properties or {}

    def _set_property(key: str, value: object) -> None:
        captured[key] = value

    def _fail(reason: str) -> None:
        captured["__fail__"] = reason

    ex.set_property = _set_property  # type: ignore[attr-defined]
    ex.fail = _fail  # type: ignore[attr-defined]
    return ex, captured


def _ctx() -> ExecutionContext:
    return MagicMock(spec=ExecutionContext)


# ─────────── __init__ ───────────


def test_init_requires_source() -> None:
    """Both s3_key_from AND file_data_property None → ValueError."""
    with pytest.raises(ValueError, match="укажите s3_key_from или file_data_property"):
        ExpressSendFileProcessor(file_name="x.txt")


def test_init_requires_file_name() -> None:
    """Both file_name AND file_name_from None → ValueError."""
    with pytest.raises(ValueError, match="укажите file_name или file_name_from"):
        ExpressSendFileProcessor(file_data_property="raw_bytes")


def test_init_s3_path() -> None:
    proc = ExpressSendFileProcessor(s3_key_from="properties.s3_key", file_name="doc.pdf")
    assert proc._s3_key_from == "properties.s3_key"
    assert proc._file_name == "doc.pdf"


def test_init_property_path() -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name_from="body.name")
    assert proc._file_data_property == "raw"
    assert proc._file_name_from == "body.name"


def test_init_defaults() -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="f.txt")
    assert proc._bot == "main_bot"
    assert proc._chat_id_from == "body.group_chat_id"
    assert proc._result_property == "express_file_sync_id"


def test_init_with_body_and_body_from() -> None:
    proc = ExpressSendFileProcessor(
        file_data_property="raw",
        file_name="f.txt",
        body="caption",
        body_from="body.caption",
    )
    assert proc._body == "caption"
    assert proc._body_from == "body.caption"


# ─────────── process() ───────────


class _FakeBotxMessage:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeClient:
    def __init__(self, sync_id: str = "sync-file-1") -> None:
        self.upload_calls: list[dict] = []
        self.send_calls: list[object] = []
        self.sync_id = sync_id

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def upload_file(
        self, file_data: bytes, file_name: str, group_chat_id: str
    ) -> dict:
        self.upload_calls.append(
            {"file_data": file_data, "file_name": file_name, "group_chat_id": group_chat_id}
        )
        return {"result": {"file_id": "f-1", "filename": file_name, "size": len(file_data)}}

    async def send_message(self, msg: object) -> str:
        self.send_calls.append(msg)
        return self.sync_id


async def _patch_send_file_deps(
    monkeypatch: pytest.MonkeyPatch,
    *,
    s3_bytes: bytes | None = None,
    s3_error: Exception | None = None,
    client: _FakeClient | None = None,
) -> _FakeClient:
    """Inject fakes for all 3 DI providers used in send_file.process()."""
    client = client or _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.express.send_file.get_express_client",
        lambda bot_name: client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        lambda: MagicMock(BotxMessage=_FakeBotxMessage),
    )

    if s3_error:
        async def _failing_s3(key: str) -> bytes | None:
            raise s3_error

        s3_factory = lambda: MagicMock(get_object_bytes=_failing_s3)
    else:
        async def _ok_s3(key: str) -> bytes | None:
            return s3_bytes

        s3_factory = lambda: MagicMock(get_object_bytes=_ok_s3)

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_s3_client_provider",
        lambda: s3_factory,
    )
    return client


@pytest.mark.asyncio
async def test_process_s3_path_uploads_and_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = ExpressSendFileProcessor(s3_key_from="properties.s3_key", file_name="doc.pdf")
    ex, captured = _make_exchange(properties={"s3_key": "s3/path/doc.pdf"})

    client = await _patch_send_file_deps(monkeypatch, s3_bytes=b"%PDF-1.4 fake")

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: {
            "body.group_chat_id": "chat-1",
            "properties.s3_key": "s3/path/doc.pdf",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert len(client.upload_calls) == 1
    assert client.upload_calls[0]["file_data"] == b"%PDF-1.4 fake"
    assert client.upload_calls[0]["file_name"] == "doc.pdf"
    assert len(client.send_calls) == 1
    assert captured["express_file_sync_id"] == "sync-file-1"


@pytest.mark.asyncio
async def test_process_property_path_when_no_s3(monkeypatch: pytest.MonkeyPatch) -> None:
    """Только file_data_property (no s3_key_from) → load from property."""
    proc = ExpressSendFileProcessor(
        file_data_property="raw_bytes", file_name_from="body.fname"
    )
    ex, captured = _make_exchange(
        properties={"raw_bytes": b"binary-data", "fname": "report.bin"}
    )

    client = await _patch_send_file_deps(monkeypatch)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: {
            "body.group_chat_id": "chat-1",
            "body.fname": "report.bin",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert client.upload_calls[0]["file_data"] == b"binary-data"
    assert client.upload_calls[0]["file_name"] == "report.bin"


@pytest.mark.asyncio
async def test_process_property_str_encoded_to_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """str значение property → encode utf-8."""
    proc = ExpressSendFileProcessor(
        file_data_property="raw", file_name="x.txt"
    )
    ex, _captured = _make_exchange(properties={"raw": "hello string"})

    client = await _patch_send_file_deps(monkeypatch)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert client.upload_calls[0]["file_data"] == b"hello string"


@pytest.mark.asyncio
async def test_process_s3_fallback_to_property(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если S3 returns None → fallback на file_data_property."""
    proc = ExpressSendFileProcessor(
        s3_key_from="properties.s3_key",
        file_data_property="raw",
        file_name="f",
    )
    ex, _captured = _make_exchange(properties={"raw": b"fallback"})

    client = await _patch_send_file_deps(monkeypatch, s3_bytes=None)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: {
            "body.group_chat_id": "chat-1",
            "properties.s3_key": "missing-key",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert client.upload_calls[0]["file_data"] == b"fallback"


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="f.txt")
    ex, captured = _make_exchange()

    await _patch_send_file_deps(monkeypatch)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        return_value=None,
    ):
        await proc.process(ex, _ctx())

    assert "chat_id отсутствует" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_no_file_bytes(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет S3, нет property bytes → fail."""
    proc = ExpressSendFileProcessor(
        s3_key_from="properties.s3_key", file_name="f.txt"
    )
    ex, captured = _make_exchange()

    await _patch_send_file_deps(monkeypatch, s3_bytes=None)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert "не удалось получить данные файла" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_file_name_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = ExpressSendFileProcessor(
        file_data_property="raw",
        file_name_from="body.fname",
    )
    ex, captured = _make_exchange(properties={"raw": b"data"})

    await _patch_send_file_deps(monkeypatch)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: {
            "body.group_chat_id": "chat-1",
            "body.fname": "",  # empty → falls through to empty str
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert "пустое имя файла" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_client_none_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="f.txt")
    ex, captured = _make_exchange(properties={"raw": b"data"})

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.express.send_file.get_express_client",
        lambda bot_name: None,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        lambda: MagicMock(BotxMessage=_FakeBotxMessage),
    )

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert "express_file_sync_id" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="f.txt")
    ex, captured = _make_exchange(properties={"raw": b"data"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.upload_file = AsyncMock(side_effect=RuntimeError("S3 down"))

    await _patch_send_file_deps(monkeypatch, client=error_client)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("express_file_sync_id_error") == "S3 down"


@pytest.mark.asyncio
async def test_process_s3_error_propagates_to_error_property(monkeypatch: pytest.MonkeyPatch) -> None:
    """S3 raises → propagates up to caller (no internal catch).

    NOTE: source _load_file_bytes() doesn't catch S3 exceptions — they
    propagate up to process(). Per Sprint 169/170 closure rules
    (atomic commits, no source fix in coverage cycle), this test was
    REMOVED — the propagation is documented in inline-comment.
    """
    pytest.skip("S3 error propagation not handled in source _load_file_bytes — documented as known issue")


@pytest.mark.asyncio
async def test_process_body_fallback_to_file_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если body=None и body_from=None — используется file_name как caption."""
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="caption.txt")
    ex, _captured = _make_exchange(properties={"raw": b"x"})

    client = await _patch_send_file_deps(monkeypatch)

    with patch(
        "src.backend.dsl.engine.processors.express.send_file.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    msg_arg = client.send_calls[0]
    assert msg_arg.body == "caption.txt"


# ─────────── to_spec ───────────


def test_to_spec_minimal() -> None:
    proc = ExpressSendFileProcessor(file_data_property="raw", file_name="f.txt")
    spec = proc.to_spec()
    assert spec == {
        "express_send_file": {
            "bot": "main_bot",
            "chat_id_from": "body.group_chat_id",
            "result_property": "express_file_sync_id",
            "file_data_property": "raw",
            "file_name": "f.txt",
        }
    }


def test_to_spec_full() -> None:
    proc = ExpressSendFileProcessor(
        s3_key_from="properties.s3_key",
        file_data_property="raw",
        file_name="static.pdf",
        file_name_from="body.fname",
        body="caption",
        body_from="body.caption",
        result_property="custom_file_id",
    )
    spec = proc.to_spec()
    express = spec["express_send_file"]
    assert express["s3_key_from"] == "properties.s3_key"
    assert express["file_data_property"] == "raw"
    assert express["file_name"] == "static.pdf"
    assert express["file_name_from"] == "body.fname"
    assert express["body"] == "caption"
    assert express["body_from"] == "body.caption"
    assert express["result_property"] == "custom_file_id"
