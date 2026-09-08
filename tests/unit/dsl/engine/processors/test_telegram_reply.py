"""Tests for src.backend.dsl.engine.processors.telegram.reply.

T3 coverage sprint cycle 13: TelegramReplyProcessor (reply на сообщение).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.reply import TelegramReplyProcessor


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


# ─────────── __init__ / to_spec ───────────


def test_init_requires_body_or_body_from() -> None:
    with pytest.raises(ValueError, match="укажите body или body_from"):
        TelegramReplyProcessor()


def test_init_with_static_body() -> None:
    proc = TelegramReplyProcessor(body="text")
    assert proc._body == "text"
    assert proc._body_from is None


def test_init_with_body_from() -> None:
    proc = TelegramReplyProcessor(body_from="body.text")
    assert proc._body is None
    assert proc._body_from == "body.text"


def test_init_defaults() -> None:
    proc = TelegramReplyProcessor(body="text")
    assert proc._bot == "main_bot"
    assert proc._source_message_id_from == "body.message.message_id"
    assert proc._chat_id_from == "body.chat_id"
    assert proc._parse_mode == "HTML"
    assert proc._result_property == "telegram_reply_message_id"


def test_to_spec_minimal() -> None:
    proc = TelegramReplyProcessor(body="hello")
    spec = proc.to_spec()
    assert spec == {
        "telegram_reply": {
            "bot": "main_bot",
            "source_message_id_from": "body.message.message_id",
            "chat_id_from": "body.chat_id",
            "parse_mode": "HTML",
            "result_property": "telegram_reply_message_id",
            "body": "hello",
        }
    }


def test_to_spec_body_from() -> None:
    proc = TelegramReplyProcessor(body_from="body.text")
    spec = proc.to_spec()
    assert spec["telegram_reply"]["body_from"] == "body.text"
    assert "body" not in spec["telegram_reply"]


# ─────────── process() ───────────


class _FakeTelegramMessage:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeClient:
    def __init__(self, message_id: int = 999) -> None:
        self.reply_calls: list[tuple[int, object]] = []
        self.message_id = message_id

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def reply(self, source_message_id: int, msg: object) -> int:
        self.reply_calls.append((source_message_id, msg))
        return self.message_id


@pytest.mark.asyncio
async def test_process_sends_reply_and_stores_message_id(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="text")
    ex, captured = _make_exchange(
        properties={"message": {"message_id": 100}, "chat_id": "chat-1"}
    )

    fake_client = _FakeClient(message_id=777)
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 100,
            "body.chat_id": "chat-1",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.reply_calls) == 1
    source_id_arg, msg_arg = fake_client.reply_calls[0]
    assert source_id_arg == 100
    assert msg_arg.chat_id == "chat-1"
    assert msg_arg.text == "text"
    assert msg_arg.parse_mode == "HTML"
    assert captured["telegram_reply_message_id"] == 777


@pytest.mark.asyncio
async def test_process_skips_when_source_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="text")
    ex, captured = _make_exchange(properties={"chat_id": "chat-1"})

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: "chat-1" if expr == "body.chat_id" else None,
    ):
        await proc.process(ex, _ctx())

    assert "source_message_id отсутствует" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_or_text_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="placeholder")  # init ok
    ex, captured = _make_exchange(properties={"message": {"message_id": 1}})

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 1,
            "body.chat_id": None,
        }.get(expr),
    ):
        # override body to None to force body_from None
        proc._body = None
        proc._body_from = ""
        await proc.process(ex, _ctx())

    assert "chat_id или текст пусты" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_uses_body_from_when_static_none(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body_from="properties.text")
    ex, _captured = _make_exchange(
        properties={"message": {"message_id": 50}, "chat_id": "chat-1", "text": "from exchange"}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 50,
            "body.chat_id": "chat-1",
            "properties.text": "from exchange",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert fake_client.reply_calls[0][1].text == "from exchange"


@pytest.mark.asyncio
async def test_process_static_body_priority(monkeypatch: pytest.MonkeyPatch) -> None:
    """body (static) wins over body_from."""
    proc = TelegramReplyProcessor(body="STATIC", body_from="properties.text")
    ex, _captured = _make_exchange(
        properties={"message": {"message_id": 1}, "chat_id": "chat-1", "text": "DYNAMIC"}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 1,
            "body.chat_id": "chat-1",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert fake_client.reply_calls[0][1].text == "STATIC"


@pytest.mark.asyncio
async def test_process_client_none_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="text")
    ex, captured = _make_exchange(
        properties={"message": {"message_id": 1}, "chat_id": "chat-1"}
    )

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 1,
            "body.chat_id": "chat-1",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert "telegram_reply_message_id" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="text")
    ex, captured = _make_exchange(
        properties={"message": {"message_id": 1}, "chat_id": "chat-1"}
    )

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.reply = AsyncMock(side_effect=RuntimeError("Bot API 502"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        MagicMock(return_value=error_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 1,
            "body.chat_id": "chat-1",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert captured.get("telegram_reply_message_id_error") == "Bot API 502"


@pytest.mark.asyncio
async def test_process_custom_result_property(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramReplyProcessor(body="text", result_property="custom_reply_id")
    ex, captured = _make_exchange(
        properties={"message": {"message_id": 1}, "chat_id": "chat-1"}
    )

    fake_client = _FakeClient(message_id=42)
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: {
            "body.message.message_id": 1,
            "body.chat_id": "chat-1",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert captured.get("custom_reply_id") == 42


@pytest.mark.asyncio
async def test_process_source_message_id_coerced_to_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """source_message_id coerced to int before passing to client."""
    proc = TelegramReplyProcessor(body="text")
    ex, _captured = _make_exchange(properties={"chat_id": "chat-1"})

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.reply.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMessage=_FakeTelegramMessage)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.reply.resolve_value",
        lambda exch, expr: "12345" if expr == "body.message.message_id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    source_id_arg = fake_client.reply_calls[0][0]
    assert source_id_arg == 12345
    assert isinstance(source_id_arg, int)
