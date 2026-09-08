"""Tests for src.backend.dsl.engine.processors.telegram.send.

T3 coverage sprint cycle 18: TelegramSendProcessor (Telegram message send).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.send import TelegramSendProcessor


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


def test_init_requires_body_or_body_from() -> None:
    with pytest.raises(ValueError, match="укажите body или body_from"):
        TelegramSendProcessor()


def test_init_defaults() -> None:
    proc = TelegramSendProcessor(body="text")
    assert proc._bot == "main_bot"
    assert proc._chat_id_from == "body.chat_id"
    assert proc._parse_mode == "HTML"
    assert proc._inline_keyboard == []
    assert proc._reply_keyboard == []
    assert proc._disable_notification is False
    assert proc._disable_web_page_preview is False
    assert proc._result_property == "telegram_message_id"


def test_init_with_inline_keyboard() -> None:
    proc = TelegramSendProcessor(
        body="x", inline_keyboard=[[{"text": "btn"}]]
    )
    assert proc._inline_keyboard == [[{"text": "btn"}]]


def test_init_with_reply_keyboard() -> None:
    proc = TelegramSendProcessor(body="x", reply_keyboard=[["btn1"]])
    assert proc._reply_keyboard == [["btn1"]]


def test_init_with_disable_flags() -> None:
    proc = TelegramSendProcessor(
        body="x",
        disable_notification=True,
        disable_web_page_preview=True,
    )
    assert proc._disable_notification is True
    assert proc._disable_web_page_preview is True


# ─────────── to_spec ───────────


def test_to_spec_minimal() -> None:
    proc = TelegramSendProcessor(body="x")
    spec = proc.to_spec()
    assert spec == {
        "telegram_send": {
            "bot": "main_bot",
            "chat_id_from": "body.chat_id",
            "parse_mode": "HTML",
            "disable_notification": False,
            "disable_web_page_preview": False,
            "result_property": "telegram_message_id",
            "body": "x",
        }
    }


def test_to_spec_with_body_from() -> None:
    proc = TelegramSendProcessor(body_from="properties.text")
    spec = proc.to_spec()
    assert spec["telegram_send"]["body_from"] == "properties.text"


def test_to_spec_with_keyboards() -> None:
    proc = TelegramSendProcessor(
        body="x",
        inline_keyboard=[[{"text": "btn"}]],
        reply_keyboard=[["text1"]],
    )
    spec = proc.to_spec()
    assert spec["telegram_send"]["inline_keyboard"] == [[{"text": "btn"}]]
    assert spec["telegram_send"]["reply_keyboard"] == [["text1"]]


# ─────────── _normalize_btn ───────────


def test_normalize_btn_filters_unknown() -> None:
    raw = {"text": "btn", "url": "http://x", "weird": "skip"}
    result = TelegramSendProcessor._normalize_btn(raw)
    assert result == {"text": "btn", "url": "http://x"}


def test_normalize_btn_empty() -> None:
    assert TelegramSendProcessor._normalize_btn({}) == {}


# ─────────── process() ───────────


class _FakeTelegramButton:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeTelegramMessage:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeClient:
    def __init__(self, message_id: int = 555) -> None:
        self.send_calls: list[object] = []
        self.message_id = message_id

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send_message(self, msg: object) -> int:
        self.send_calls.append(msg)
        return self.message_id


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(
            return_value=MagicMock(
                TelegramButton=_FakeTelegramButton, TelegramMessage=_FakeTelegramMessage
            )
        ),
    )


@pytest.mark.asyncio
async def test_process_sends_message(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="hello")
    ex, captured = _make_exchange(properties={"chat_id": "chat-1"})

    fake_client = _FakeClient(message_id=999)
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.send.resolve_value",
            lambda exch, expr: "chat-1",
        )
        await proc.process(ex, _ctx())

    assert len(fake_client.send_calls) == 1
    msg = fake_client.send_calls[0]
    assert msg.chat_id == "chat-1"
    assert msg.text == "hello"
    assert msg.parse_mode == "HTML"
    assert captured["telegram_message_id"] == 999


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="text")
    ex, captured = _make_exchange()

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.send.resolve_value",
        MagicMock(return_value=None),
    )
        await proc.process(ex, _ctx())

    assert fake_client.send_calls == []
    assert "не удалось извлечь chat_id" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_text_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="placeholder")  # init ok
    ex, captured = _make_exchange(properties={"chat_id": "chat-1"})

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.send.resolve_value",
            lambda exch, expr: "chat-1" if expr == "body.chat_id" else None,
        )
        # override body to None to force body_from path
        proc._body = None
        proc._body_from = ""
        await proc.process(ex, _ctx())

    assert fake_client.send_calls == []
    assert "текст сообщения пуст" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_uses_body_from(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body_from="properties.text")
    ex, _captured = _make_exchange(
        properties={"chat_id": "chat-1", "text": "from exchange"}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.send.resolve_value",
            lambda exch, expr: {
                "body.chat_id": "chat-1",
                "properties.text": "from exchange",
            }.get(expr),
        )
        await proc.process(ex, _ctx())

    assert fake_client.send_calls[0].text == "from exchange"


@pytest.mark.asyncio
async def test_process_static_body_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="STATIC", body_from="properties.text")
    ex, _captured = _make_exchange(
        properties={"chat_id": "chat-1", "text": "DYNAMIC"}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.send.resolve_value",
            lambda exch, expr: {
                "body.chat_id": "chat-1",
                "properties.text": "DYNAMIC",
            }.get(expr),
        )
        await proc.process(ex, _ctx())

    assert fake_client.send_calls[0].text == "STATIC"


@pytest.mark.asyncio
async def test_process_with_inline_keyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(
        body="x",
        inline_keyboard=[[{"text": "btn1", "url": "http://example.com"}]],
    )
    ex, _captured = _make_exchange(properties={"chat_id": "chat-1"})

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.send.resolve_value",
        MagicMock(return_value="chat-1"),
    )
        await proc.process(ex, _ctx())

    msg = fake_client.send_calls[0]
    assert len(msg.inline_keyboard) == 1
    assert len(msg.inline_keyboard[0]) == 1
    assert msg.inline_keyboard[0][0].text == "btn1"
    assert msg.inline_keyboard[0][0].url == "http://example.com"


@pytest.mark.asyncio
async def test_process_client_none_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="x")
    ex, captured = _make_exchange(properties={"chat_id": "chat-1"})

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        MagicMock(return_value=None),
    )
    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.send.resolve_value",
        MagicMock(return_value="chat-1"),
    )
        await proc.process(ex, _ctx())

    assert "telegram_message_id" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="x")
    ex, captured = _make_exchange(properties={"chat_id": "chat-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.send_message = AsyncMock(side_effect=RuntimeError("Bot API 429"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        MagicMock(return_value=error_client),
    )
    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.send.resolve_value",
        MagicMock(return_value="chat-1"),
    )
        await proc.process(ex, _ctx())

    assert captured.get("telegram_message_id_error") == "Bot API 429"


@pytest.mark.asyncio
async def test_process_chat_id_coerced_to_str(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramSendProcessor(body="x")
    ex, _captured = _make_exchange()

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.send.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.send.resolve_value",
            lambda exch, expr: 123456 if expr == "body.chat_id" else None,
        )
        await proc.process(ex, _ctx())

    msg = fake_client.send_calls[0]
    assert msg.chat_id == "123456"
    assert isinstance(msg.chat_id, str)
