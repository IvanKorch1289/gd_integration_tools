"""Smoke unit-тесты для Telegram DSL-процессоров (W15.3).

Покрытие 7 процессоров (по аналогии с Express):
    * TelegramSendProcessor
    * TelegramReplyProcessor
    * TelegramEditProcessor
    * TelegramTypingProcessor
    * TelegramSendFileProcessor
    * TelegramMentionProcessor
    * TelegramStatusProcessor

Подход:
    * ``get_telegram_client`` подменяется на ``FakeTelegramClient`` (AsyncMock).
    * Используются реальные ``Exchange`` и ``ExecutionContext``.
    * Тестируются: to_spec roundtrip, basic process, error path.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.telegram import (
    TelegramEditProcessor,
    TelegramMentionProcessor,
    TelegramReplyProcessor,
    TelegramSendFileProcessor,
    TelegramSendProcessor,
    TelegramStatusProcessor,
    TelegramTypingProcessor,
)


class FakeTelegramClient:
    """In-memory заглушка ``TelegramBotClient`` с async context-manager."""

    def __init__(
        self,
        *,
        send_result: int = 100,
        reply_result: int = 200,
        send_doc_result: int = 300,
        get_me_result: dict[str, Any] | None = None,
    ) -> None:
        self.send_message = AsyncMock(return_value=send_result)
        self.reply = AsyncMock(return_value=reply_result)
        self.edit_message = AsyncMock(return_value=None)
        self.send_chat_action = AsyncMock(return_value=None)
        self.send_document = AsyncMock(return_value=send_doc_result)
        self.get_me = AsyncMock(
            return_value=get_me_result
            or {"id": 12345, "is_bot": True, "username": "test_bot"}
        )

    async def __aenter__(self) -> FakeTelegramClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        return None


def _make_exchange(
    body: Any = None, headers: dict[str, Any] | None = None
) -> Exchange[Any]:
    """Создаёт Exchange с заданным in_message."""
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _make_context() -> ExecutionContext:
    """Создаёт реальный ExecutionContext (без mock)."""
    return ExecutionContext()


@pytest.fixture
def fake_client() -> FakeTelegramClient:
    """Дефолтный fake-клиент."""
    return FakeTelegramClient()


def _install_client(
    monkeypatch: pytest.MonkeyPatch, module: str, client: FakeTelegramClient
) -> None:
    """Подменяет ``get_telegram_client`` в модуле процессора."""
    monkeypatch.setattr(
        f"src.backend.dsl.engine.processors.telegram.{module}.get_telegram_client",
        lambda bot_name="main_bot": client,
        raising=True,
    )


# ── TelegramSendProcessor ────────────────────────────────────────────────


class TestTelegramSendProcessor:
    def test_requires_body_or_body_from(self) -> None:
        with pytest.raises(ValueError, match="body или body_from"):
            TelegramSendProcessor()

    def test_to_spec_round_trip(self) -> None:
        proc = TelegramSendProcessor(
            bot="main_bot",
            chat_id_from="body.chat_id",
            body="hi",
            inline_keyboard=[[{"text": "Y", "callback_data": "y"}]],
            disable_notification=True,
        )
        spec = proc.to_spec()
        assert "telegram_send" in spec
        payload = spec["telegram_send"]
        assert payload["body"] == "hi"
        assert payload["disable_notification"] is True
        assert payload["inline_keyboard"] == [[{"text": "Y", "callback_data": "y"}]]

    async def test_send_static_body(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "send", fake_client)
        proc = TelegramSendProcessor(body="hello", chat_id_from="body.chat_id")
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        fake_client.send_message.assert_awaited_once()
        msg = fake_client.send_message.await_args.args[0]
        assert msg.chat_id == "c1"
        assert msg.text == "hello"
        assert exchange.get_property("telegram_message_id") == 100

    async def test_send_missing_chat_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "send", fake_client)
        proc = TelegramSendProcessor(body="hi")
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed
        fake_client.send_message.assert_not_awaited()

    async def test_send_handles_client_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "send", fake_client)
        fake_client.send_message.side_effect = RuntimeError("boom")
        proc = TelegramSendProcessor(body="hi", chat_id_from="body.chat_id")
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        assert exchange.get_property("telegram_message_id_error") == "boom"


# ── TelegramReplyProcessor ───────────────────────────────────────────────


class TestTelegramReplyProcessor:
    def test_to_spec_round_trip(self) -> None:
        proc = TelegramReplyProcessor(body="re")
        spec = proc.to_spec()
        assert "telegram_reply" in spec
        assert spec["telegram_reply"]["body"] == "re"

    async def test_reply_with_source_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "reply", fake_client)
        proc = TelegramReplyProcessor(
            body="re", source_message_id_from="body.msg_id", chat_id_from="body.chat_id"
        )
        exchange = _make_exchange(body={"msg_id": 5, "chat_id": "c1"})

        await proc.process(exchange, _make_context())

        fake_client.reply.assert_awaited_once()
        source_id, msg = fake_client.reply.await_args.args
        assert source_id == 5
        assert msg.chat_id == "c1"
        assert exchange.get_property("telegram_reply_message_id") == 200


# ── TelegramEditProcessor ────────────────────────────────────────────────


class TestTelegramEditProcessor:
    def test_to_spec_round_trip(self) -> None:
        proc = TelegramEditProcessor(body="new")
        spec = proc.to_spec()
        assert "telegram_edit" in spec
        assert spec["telegram_edit"]["body"] == "new"

    async def test_edit_with_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "edit", fake_client)
        proc = TelegramEditProcessor(body="updated")
        exchange = _make_exchange(body={"chat_id": "c1"})
        exchange.set_property("telegram_message_id", 7)

        await proc.process(exchange, _make_context())

        fake_client.edit_message.assert_awaited_once()
        kwargs = fake_client.edit_message.await_args.kwargs
        assert kwargs["chat_id"] == "c1"
        assert kwargs["message_id"] == 7
        assert kwargs["text"] == "updated"

    async def test_edit_skips_when_no_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "edit", fake_client)
        proc = TelegramEditProcessor()
        exchange = _make_exchange(body={"chat_id": "c1"})
        exchange.set_property("telegram_message_id", 7)

        await proc.process(exchange, _make_context())

        fake_client.edit_message.assert_not_awaited()


# ── TelegramTypingProcessor ──────────────────────────────────────────────


class TestTelegramTypingProcessor:
    def test_invalid_action_raises(self) -> None:
        with pytest.raises(ValueError, match="action"):
            TelegramTypingProcessor(action="invalid")

    def test_to_spec_round_trip(self) -> None:
        proc = TelegramTypingProcessor(action="upload_photo")
        spec = proc.to_spec()
        assert spec["telegram_typing"]["action"] == "upload_photo"

    async def test_typing_sends_chat_action(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "typing", fake_client)
        proc = TelegramTypingProcessor(action="typing")
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        fake_client.send_chat_action.assert_awaited_once_with("c1", "typing")


# ── TelegramSendFileProcessor ────────────────────────────────────────────


class TestTelegramSendFileProcessor:
    def test_requires_source(self) -> None:
        with pytest.raises(ValueError, match="s3_key_from или file_data_property"):
            TelegramSendFileProcessor(file_name="x.txt")

    def test_requires_file_name(self) -> None:
        with pytest.raises(ValueError, match="file_name или file_name_from"):
            TelegramSendFileProcessor(file_data_property="data")

    def test_to_spec_round_trip(self) -> None:
        proc = TelegramSendFileProcessor(
            file_data_property="data", file_name="x.txt", body="cap"
        )
        spec = proc.to_spec()
        assert spec["telegram_send_file"]["file_name"] == "x.txt"
        assert spec["telegram_send_file"]["body"] == "cap"

    async def test_send_file_from_property(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "send_file", fake_client)
        proc = TelegramSendFileProcessor(
            file_data_property="data", file_name="report.pdf", body="cap"
        )
        exchange = _make_exchange(body={"chat_id": "c1"})
        exchange.set_property("data", b"PDF-bytes")

        await proc.process(exchange, _make_context())

        fake_client.send_document.assert_awaited_once()
        kwargs = fake_client.send_document.await_args.kwargs
        assert kwargs["file_data"] == b"PDF-bytes"
        assert kwargs["file_name"] == "report.pdf"
        assert kwargs["caption"] == "cap"
        assert exchange.get_property("telegram_file_message_id") == 300


# ── TelegramMentionProcessor ─────────────────────────────────────────────


class TestTelegramMentionProcessor:
    def test_invalid_parse_mode_raises(self) -> None:
        with pytest.raises(ValueError, match="parse_mode"):
            TelegramMentionProcessor(user_id_from="body.uid", parse_mode="bbcode")

    def test_to_spec_round_trip(self) -> None:
        proc = TelegramMentionProcessor(
            user_id_from="body.uid",
            display_name_from="body.name",
            append=True,
        )
        spec = proc.to_spec()
        assert spec["telegram_mention"]["user_id_from"] == "body.uid"
        assert spec["telegram_mention"]["append"] is True

    async def test_mention_writes_property_markdown(self) -> None:
        proc = TelegramMentionProcessor(
            user_id_from="body.uid",
            display_name_from="body.name",
            parse_mode="MarkdownV2",
        )
        exchange = _make_exchange(body={"uid": 42, "name": "Alice"})

        await proc.process(exchange, _make_context())

        fragment = exchange.get_property("telegram_mention")
        assert fragment == "[Alice](tg://user?id=42)"

    async def test_mention_html(self) -> None:
        proc = TelegramMentionProcessor(
            user_id_from="body.uid",
            display_name_from="body.name",
            parse_mode="HTML",
        )
        exchange = _make_exchange(body={"uid": 42, "name": "Bob"})

        await proc.process(exchange, _make_context())

        fragment = exchange.get_property("telegram_mention")
        assert fragment == '<a href="tg://user?id=42">Bob</a>'

    async def test_mention_append(self) -> None:
        proc = TelegramMentionProcessor(
            user_id_from="body.uid",
            display_name_from="body.name",
            append=True,
        )
        exchange = _make_exchange(body={"uid": 1, "name": "X"})
        exchange.set_property("telegram_mention", "prev")

        await proc.process(exchange, _make_context())

        assert exchange.get_property("telegram_mention") == "prev [X](tg://user?id=1)"

    async def test_mention_skip_when_user_id_invalid(self) -> None:
        proc = TelegramMentionProcessor(user_id_from="body.uid")
        exchange = _make_exchange(body={"uid": "abc"})

        await proc.process(exchange, _make_context())

        assert exchange.get_property("telegram_mention") is None


# ── TelegramStatusProcessor ──────────────────────────────────────────────


class TestTelegramStatusProcessor:
    def test_to_spec_round_trip(self) -> None:
        proc = TelegramStatusProcessor()
        spec = proc.to_spec()
        assert "telegram_status" in spec
        assert spec["telegram_status"]["bot"] == "main_bot"

    async def test_status_writes_profile(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeTelegramClient,
    ) -> None:
        _install_client(monkeypatch, "status", fake_client)
        proc = TelegramStatusProcessor()
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        fake_client.get_me.assert_awaited_once()
        profile = exchange.get_property("telegram_bot_profile")
        assert profile is not None
        assert profile["username"] == "test_bot"
