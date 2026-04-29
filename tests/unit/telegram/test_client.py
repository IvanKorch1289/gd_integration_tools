"""Smoke unit-тесты для ``TelegramBotClient`` (W15.3).

Покрытие:
    * ``send_message`` — POST /sendMessage с inline_keyboard.
    * ``reply`` — добавление reply_to_message_id.
    * ``edit_message`` — POST /editMessageText.
    * ``delete_message`` — POST /deleteMessage.
    * ``send_chat_action`` — POST /sendChatAction.
    * ``send_document`` — multipart upload.
    * ``get_me`` — health-check.
    * Обработка ``ok=false`` и HTTP 4xx.
    * Контекст-менеджер открытия/закрытия HTTP-клиента.

Подмена HTTP-транспорта через ``httpx.MockTransport``.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from src.infrastructure.clients.external.telegram_bot import (
    TelegramBotClient,
    TelegramBotConfig,
    TelegramButton,
    TelegramMention,
    TelegramMessage,
)


@pytest.fixture
def bot_config() -> TelegramBotConfig:
    """Тестовая конфигурация Telegram бота."""
    return TelegramBotConfig(
        bot_id="12345",
        secret_key="ABCDEF",  # noqa: S106
        base_url="https://api.telegram.org",
        timeout=5.0,
    )


def _make_client(
    config: TelegramBotConfig, handler: Any
) -> TelegramBotClient:
    """Создаёт TelegramBotClient с подменённым transport."""
    client = TelegramBotClient(config)
    transport = (
        handler
        if isinstance(handler, httpx.MockTransport)
        else httpx.MockTransport(handler)
    )
    client._http = httpx.AsyncClient(  # noqa: SLF001
        base_url=f"{config.base_url}/bot{config.token}",
        timeout=config.timeout,
        transport=transport,
    )
    return client


# ── Models ──────────────────────────────────────────────────────────────


class TestModels:
    """Тесты моделей dataclass."""

    def test_token_property(self, bot_config: TelegramBotConfig) -> None:
        """``token`` собирается как ``{bot_id}:{secret_key}``."""
        assert bot_config.token == "12345:ABCDEF"

    def test_button_to_dict_url(self) -> None:
        """``TelegramButton`` сериализуется только с заданными полями."""
        btn = TelegramButton(text="Open", url="https://example.com")
        assert btn.to_dict() == {"text": "Open", "url": "https://example.com"}

    def test_button_to_dict_callback(self) -> None:
        """callback_data сериализуется при задании."""
        btn = TelegramButton(text="OK", callback_data="ok_pressed")
        assert btn.to_dict() == {"text": "OK", "callback_data": "ok_pressed"}

    def test_button_to_dict_web_app(self) -> None:
        """``web_app_url`` оборачивается в ``{web_app: {url}}``."""
        btn = TelegramButton(text="Open WebApp", web_app_url="https://app.example.com")
        assert btn.to_dict()["web_app"] == {"url": "https://app.example.com"}

    def test_mention_markdown(self) -> None:
        """MarkdownV2 mention возвращает ``[name](tg://user?id=...)``."""
        m = TelegramMention(user_id=7, display_name="Alice", parse_mode="MarkdownV2")
        assert m.to_inline() == "[Alice](tg://user?id=7)"

    def test_mention_html(self) -> None:
        """HTML mention возвращает ``<a href=...>name</a>``."""
        m = TelegramMention(user_id=7, display_name="Alice", parse_mode="HTML")
        assert "<a href=\"tg://user?id=7\">Alice</a>" == m.to_inline()

    def test_message_payload_minimal(self) -> None:
        """Минимальный payload содержит только chat_id+text+parse_mode."""
        msg = TelegramMessage(chat_id="@chan", text="Hi")
        payload = msg.to_payload()
        assert payload == {"chat_id": "@chan", "text": "Hi", "parse_mode": "HTML"}

    def test_message_payload_with_inline_keyboard(self) -> None:
        """Inline keyboard сериализуется в reply_markup.inline_keyboard."""
        msg = TelegramMessage(
            chat_id="c1",
            text="x",
            inline_keyboard=[[TelegramButton(text="Y", callback_data="y")]],
        )
        markup = msg.to_payload()["reply_markup"]
        assert markup["inline_keyboard"] == [[{"text": "Y", "callback_data": "y"}]]

    def test_message_payload_reply_keyboard_when_no_inline(self) -> None:
        """Reply keyboard добавляется только когда нет inline."""
        msg = TelegramMessage(
            chat_id="c1",
            text="x",
            reply_keyboard=[["Yes", "No"]],
        )
        markup = msg.to_payload()["reply_markup"]
        assert markup["keyboard"] == [[{"text": "Yes"}, {"text": "No"}]]
        assert markup["resize_keyboard"] is True


# ── send_message ─────────────────────────────────────────────────────────


class TestSendMessage:
    """Тесты ``send_message`` через MockTransport."""

    async def test_send_message_basic(self, bot_config: TelegramBotConfig) -> None:
        """POST /sendMessage с правильным URL и body."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

        client = _make_client(bot_config, handler)
        message_id = await client.send_message(
            TelegramMessage(chat_id="@chan", text="hello")
        )
        assert message_id == 42
        assert captured["method"] == "POST"
        assert captured["path"] == "/bot12345:ABCDEF/sendMessage"
        assert captured["json"] == {
            "chat_id": "@chan",
            "text": "hello",
            "parse_mode": "HTML",
        }

    async def test_send_message_with_inline_keyboard(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """Inline keyboard передаётся в reply_markup."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

        client = _make_client(bot_config, handler)
        await client.send_message(
            TelegramMessage(
                chat_id="c1",
                text="x",
                inline_keyboard=[[TelegramButton(text="Y", callback_data="y")]],
            )
        )
        assert captured["json"]["reply_markup"]["inline_keyboard"] == [
            [{"text": "Y", "callback_data": "y"}]
        ]

    async def test_send_message_telegram_error(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """``ok=false`` → ``HTTPStatusError`` с описанием."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"ok": False, "description": "chat not found"}
            )

        client = _make_client(bot_config, handler)
        with pytest.raises(httpx.HTTPStatusError, match="chat not found"):
            await client.send_message(TelegramMessage(chat_id="x", text="y"))

    async def test_send_message_http_error(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """HTTP 4xx → ``HTTPStatusError``."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"ok": False, "description": "unauthorized"})

        client = _make_client(bot_config, handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(TelegramMessage(chat_id="x", text="y"))


# ── reply / edit / delete ───────────────────────────────────────────────


class TestReplyEditDelete:
    """Reply, edit, delete сообщений."""

    async def test_reply_includes_reply_to_message_id(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """Reply payload содержит ``reply_to_message_id``."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 99}})

        client = _make_client(bot_config, handler)
        msg_id = await client.reply(50, TelegramMessage(chat_id="c1", text="re"))
        assert msg_id == 99
        assert captured["json"]["reply_to_message_id"] == 50

    async def test_edit_message_text(self, bot_config: TelegramBotConfig) -> None:
        """edit_message с text → POST /editMessageText."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        client = _make_client(bot_config, handler)
        await client.edit_message(chat_id="c1", message_id=7, text="new")
        assert captured["path"] == "/bot12345:ABCDEF/editMessageText"
        assert captured["json"]["text"] == "new"

    async def test_edit_message_only_keyboard(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """edit_message без text → POST /editMessageReplyMarkup."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        client = _make_client(bot_config, handler)
        await client.edit_message(
            chat_id="c1",
            message_id=7,
            inline_keyboard=[[TelegramButton(text="OK", callback_data="ok")]],
        )
        assert captured["path"] == "/bot12345:ABCDEF/editMessageReplyMarkup"
        assert "text" not in captured["json"]

    async def test_delete_message(self, bot_config: TelegramBotConfig) -> None:
        """delete_message шлёт chat_id и message_id."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        client = _make_client(bot_config, handler)
        await client.delete_message("c1", 99)
        assert captured["path"] == "/bot12345:ABCDEF/deleteMessage"
        assert captured["json"] == {"chat_id": "c1", "message_id": 99}


# ── chat_action / send_document / get_me ────────────────────────────────


class TestExtra:
    """Дополнительные методы."""

    async def test_send_chat_action(self, bot_config: TelegramBotConfig) -> None:
        """sendChatAction с action=typing."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"ok": True, "result": True})

        client = _make_client(bot_config, handler)
        await client.send_chat_action("c1", "typing")
        assert captured["json"] == {"chat_id": "c1", "action": "typing"}

    async def test_send_document_multipart(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """sendDocument отправляет multipart с файлом."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["content_type"] = request.headers.get("content-type", "")
            captured["body"] = request.content
            return httpx.Response(
                200, json={"ok": True, "result": {"message_id": 333}}
            )

        client = _make_client(bot_config, handler)
        msg_id = await client.send_document(
            chat_id="c1", file_data=b"hello", file_name="x.txt", caption="cap"
        )
        assert msg_id == 333
        assert captured["path"] == "/bot12345:ABCDEF/sendDocument"
        assert captured["content_type"].startswith("multipart/form-data")
        assert b"hello" in captured["body"]

    async def test_get_me(self, bot_config: TelegramBotConfig) -> None:
        """getMe возвращает профиль бота."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"id": 12345, "is_bot": True, "username": "test_bot"},
                },
            )

        client = _make_client(bot_config, handler)
        profile = await client.get_me()
        assert profile["username"] == "test_bot"


# ── Context manager ──────────────────────────────────────────────────────


class TestContextManager:
    """Async with open/close семантика."""

    async def test_context_manager_lifecycle(
        self, bot_config: TelegramBotConfig
    ) -> None:
        """``async with`` создаёт и закрывает HTTP-клиент."""
        client = TelegramBotClient(bot_config)
        assert client._http is None  # noqa: SLF001
        async with client as opened:
            assert opened is client
            assert client._http is not None  # noqa: SLF001
        assert client._http is None  # noqa: SLF001

    def test_http_property_lazy_init(self, bot_config: TelegramBotConfig) -> None:
        """``client.http`` создаёт временный AsyncClient если не открыт."""
        client = TelegramBotClient(bot_config)
        http = client.http
        assert isinstance(http, httpx.AsyncClient)
        assert client.http is http
