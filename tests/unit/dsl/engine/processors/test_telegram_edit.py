"""Tests for src.backend.dsl.engine.processors.telegram.edit.

T3 coverage sprint cycle 11: TelegramEditProcessor (edit Telegram message).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.edit import TelegramEditProcessor


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


def test_init_defaults() -> None:
    proc = TelegramEditProcessor()
    assert proc._bot == "main_bot"
    assert proc._chat_id_from == "body.chat_id"
    assert proc._message_id_from == "properties.telegram_message_id"
    assert proc._parse_mode == "HTML"
    assert proc._body is None
    assert proc._body_from is None
    assert proc._inline_keyboard is None


def test_init_with_body_and_parse_mode() -> None:
    proc = TelegramEditProcessor(body="text", parse_mode="MarkdownV2")
    assert proc._body == "text"
    assert proc._parse_mode == "MarkdownV2"


def test_init_with_inline_keyboard() -> None:
    proc = TelegramEditProcessor(
        inline_keyboard=[[{"text": "btn", "callback_data": "x"}]]
    )
    assert proc._inline_keyboard == [[{"text": "btn", "callback_data": "x"}]]


def test_to_spec_minimal() -> None:
    proc = TelegramEditProcessor()
    spec = proc.to_spec()
    assert spec == {
        "telegram_edit": {
            "bot": "main_bot",
            "chat_id_from": "body.chat_id",
            "message_id_from": "properties.telegram_message_id",
            "parse_mode": "HTML",
        }
    }


def test_to_spec_full() -> None:
    proc = TelegramEditProcessor(
        body="static",
        body_from="body.dyn",
        inline_keyboard=[[{"text": "btn"}]],
        parse_mode="Markdown",
    )
    spec = proc.to_spec()
    assert spec == {
        "telegram_edit": {
            "bot": "main_bot",
            "chat_id_from": "body.chat_id",
            "message_id_from": "properties.telegram_message_id",
            "parse_mode": "Markdown",
            "body": "static",
            "body_from": "body.dyn",
            "inline_keyboard": [[{"text": "btn"}]],
        }
    }


def test_to_spec_body_only() -> None:
    proc = TelegramEditProcessor(body="x")
    spec = proc.to_spec()
    assert spec["telegram_edit"]["body"] == "x"
    assert "body_from" not in spec["telegram_edit"]


# ─────────── _normalize_btn ───────────


def test_normalize_btn_filters_unknown_keys() -> None:
    raw = {"text": "btn", "url": "http://x", "unknown_key": "skip"}
    result = TelegramEditProcessor._normalize_btn(raw)
    assert result == {"text": "btn", "url": "http://x"}


def test_normalize_btn_all_allowed() -> None:
    raw = {
        "text": "btn",
        "url": "http://x",
        "callback_data": "cb",
        "switch_inline_query": "q",
        "web_app_url": "wa",
    }
    result = TelegramEditProcessor._normalize_btn(raw)
    assert result == raw


def test_normalize_btn_empty() -> None:
    assert TelegramEditProcessor._normalize_btn({}) == {}


def test_normalize_btn_no_allowed() -> None:
    assert TelegramEditProcessor._normalize_btn({"foo": "bar"}) == {}


# ─────────── process() ───────────


class _FakeTelegramButton:
    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeClient:
    def __init__(self) -> None:
        self.edit_calls: list[dict] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def edit_message(
        self, *, chat_id: str, message_id: int, text: str | None, **kwargs: object
    ) -> None:
        self.edit_calls.append(
            {"chat_id": chat_id, "message_id": message_id, "text": text, **kwargs}
        )


@pytest.mark.asyncio
async def test_process_edits_message(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body="new text")
    ex, _captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 456}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        lambda bot_name: fake_client,
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {
            "body.chat_id": "123",
            "properties.telegram_message_id": 456,
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.edit_calls) == 1
    call = fake_client.edit_calls[0]
    assert call["chat_id"] == "123"
    assert call["message_id"] == 456
    assert call["text"] == "new text"
    assert call["parse_mode"] == "HTML"
    assert call["inline_keyboard"] is None


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body="text")
    ex, captured = _make_exchange(properties={"telegram_message_id": 1})

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: 1 if expr == "properties.telegram_message_id" else None,
    ):
        await proc.process(ex, _ctx())

    assert "chat_id или message_id отсутствуют" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_message_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body="text")
    ex, captured = _make_exchange(properties={"chat_id": "123"})

    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: "123" if expr == "body.chat_id" else None,
    ):
        await proc.process(ex, _ctx())

    assert "chat_id или message_id отсутствуют" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_uses_body_from_when_static_none(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body_from="properties.text")
    ex, _captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 1, "text": "dynamic"}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=fake_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {
            "body.chat_id": "123",
            "properties.telegram_message_id": 1,
            "properties.text": "dynamic",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert fake_client.edit_calls[0]["text"] == "dynamic"


@pytest.mark.asyncio
async def test_process_no_fields_skips_edit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если text=None и keyboard=None → skip edit."""
    proc = TelegramEditProcessor()  # no body, no keyboard
    ex, _captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 1}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=fake_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {
            "body.chat_id": "123",
            "properties.telegram_message_id": 1,
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert fake_client.edit_calls == []


@pytest.mark.asyncio
async def test_process_with_inline_keyboard(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(
        body="text",
        inline_keyboard=[[{"text": "btn1", "callback_data": "x"}]],
    )
    ex, _captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 1}
    )

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=fake_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {
            "body.chat_id": "123",
            "properties.telegram_message_id": 1,
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    call = fake_client.edit_calls[0]
    assert call["inline_keyboard"] is not None
    assert len(call["inline_keyboard"]) == 1
    assert len(call["inline_keyboard"][0]) == 1
    assert call["inline_keyboard"][0][0].text == "btn1"
    assert call["inline_keyboard"][0][0].callback_data == "x"


@pytest.mark.asyncio
async def test_process_client_none_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body="text")
    ex, captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 1}
    )

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=None),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {"body.chat_id": "123", "properties.telegram_message_id": 1}.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert "telegram_edit_error" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramEditProcessor(body="text")
    ex, captured = _make_exchange(
        properties={"chat_id": "123", "telegram_message_id": 1}
    )

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.edit_message = AsyncMock(side_effect=RuntimeError("Bot API 503"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=error_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {"body.chat_id": "123", "properties.telegram_message_id": 1}.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert captured.get("telegram_edit_error") == "Bot API 503"


@pytest.mark.asyncio
async def test_process_chat_id_message_id_coerced_to_str_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_id=str, message_id=int — coerced before passing to client."""
    proc = TelegramEditProcessor(body="text")
    ex, _captured = _make_exchange()

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.edit.get_telegram_client",
        MagicMock(return_value=fake_client),
    )
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramButton=_FakeTelegramButton)),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.edit.resolve_value",
        lambda exch, expr: {
            "body.chat_id": "chat-001",
            "properties.telegram_message_id": 99999,
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    call = fake_client.edit_calls[0]
    assert call["chat_id"] == "chat-001"
    assert call["message_id"] == 99999
    assert isinstance(call["message_id"], int)
