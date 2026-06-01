"""Unit-тесты для ``ExpressBotClient`` (HTTP клиент BotX API).

Покрытие:
    * Генерация JWT (HS256) с обязательными полями (iss/aud/exp/iat/nbf/jti/version).
    * ``send_message`` (sync/async endpoints).
    * ``reply`` — добавление ``source_sync_id`` в payload.
    * ``edit_message`` — выборочная сериализация полей.
    * ``send_typing`` / ``stop_typing`` — typing endpoints.
    * ``upload_file`` — multipart-загрузка.
    * ``delete_message`` / ``get_event_status`` / ``get_chat_info``
      / ``get_members`` / ``search_user``.
    * Обработка 404 в ``search_user``.
    * Контекст-менеджер открытия/закрытия HTTP-клиента.

Для подмены HTTP-транспорта используется ``httpx.MockTransport`` — при
тестировании локально создаётся экземпляр ``httpx.AsyncClient`` с этим
транспортом и присваивается ``client._http`` (private поле). Это эквивалентно
сценарию ``async with client:`` без сетевых вызовов.
"""

# ruff: noqa: S101

from __future__ import annotations

import json
from typing import Any

import httpx
import jwt
import pytest

from src.backend.infrastructure.clients.external.express_bot import (
    BotConfig,
    BotxButton,
    BotxMention,
    BotxMessage,
    ExpressBotClient,
)

# ── Фикстуры ─────────────────────────────────────────────────────────────


@pytest.fixture
def bot_config() -> BotConfig:
    """Тестовая конфигурация бота."""
    return BotConfig(
        bot_id="00000000-0000-0000-0000-000000000001",
        # Длина ≥32 байт чтобы PyJWT не выдавал InsecureKeyLengthWarning
        # (рекомендация RFC 7518 §3.2 для HS256).
        secret_key="test-secret-key-with-sufficient-length-32+",  # noqa: S106
        botx_host="cts.example.ru",
        base_url="https://cts.example.ru",
        timeout=5.0,
    )


def _make_client(
    config: BotConfig, handler: httpx.MockTransport | Any
) -> ExpressBotClient:
    """Создаёт ``ExpressBotClient`` с подменённым transport.

    ``ExpressBotClient.__init__`` не принимает ``transport``-параметр,
    поэтому подменяем приватное поле ``_http`` на ``AsyncClient`` с
    ``MockTransport``. Контекст-менеджер ``__aenter__`` повторно создаёт
    ``_http`` — поэтому в тестах вызываем методы напрямую (без ``async
    with``).
    """
    client = ExpressBotClient(config)
    transport = (
        handler
        if isinstance(handler, httpx.MockTransport)
        else httpx.MockTransport(handler)
    )
    client._http = httpx.AsyncClient(  # noqa: SLF001
        base_url=config.base_url, timeout=config.timeout, transport=transport
    )
    return client


# ── JWT generation ───────────────────────────────────────────────────────


class TestJWT:
    """Тесты генерации JWT-токенов."""

    def test_jwt_has_required_claims(self, bot_config: BotConfig) -> None:
        """JWT содержит все обязательные поля BotX API v4."""
        client = ExpressBotClient(bot_config)
        token = client._generate_token()  # noqa: SLF001
        payload = jwt.decode(
            token,
            bot_config.secret_key,
            algorithms=["HS256"],
            audience=bot_config.botx_host,
        )
        assert payload["iss"] == bot_config.bot_id
        assert payload["aud"] == bot_config.botx_host
        assert payload["version"] == 2
        assert "exp" in payload and "iat" in payload and "nbf" in payload
        assert "jti" in payload
        assert payload["exp"] > payload["iat"]

    def test_jwt_jti_is_unique(self, bot_config: BotConfig) -> None:
        """``jti`` уникален для каждого вызова."""
        client = ExpressBotClient(bot_config)
        t1 = client._generate_token()  # noqa: SLF001
        t2 = client._generate_token()  # noqa: SLF001
        p1 = jwt.decode(t1, bot_config.secret_key, algorithms=["HS256"], audience=bot_config.botx_host)
        p2 = jwt.decode(t2, bot_config.secret_key, algorithms=["HS256"], audience=bot_config.botx_host)
        assert p1["jti"] != p2["jti"]

    def test_auth_headers_bearer_prefix(self, bot_config: BotConfig) -> None:
        """``Authorization`` header — Bearer-токен."""
        client = ExpressBotClient(bot_config)
        headers = client._auth_headers()  # noqa: SLF001
        assert headers["Authorization"].startswith("Bearer ")


# ── send_message ─────────────────────────────────────────────────────────


class TestSendMessage:
    """Тесты ``send_message``."""

    async def test_send_message_async_endpoint(self, bot_config: BotConfig) -> None:
        """Async endpoint: POST /api/v4/botx/notifications/direct."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["headers"] = dict(request.headers)
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"result": {"sync_id": "sid-001"}})

        client = _make_client(bot_config, handler)
        sync_id = await client.send_message(
            BotxMessage(group_chat_id="chat-1", body="hello")
        )
        assert sync_id == "sid-001"
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v4/botx/notifications/direct"
        assert captured["headers"]["authorization"].startswith("Bearer ")
        body = captured["json"]
        assert body["group_chat_id"] == "chat-1"
        assert body["notification"]["body"] == "hello"
        assert body["notification"]["status"] == "ok"

    async def test_send_message_sync_endpoint(self, bot_config: BotConfig) -> None:
        """Sync endpoint: POST /api/v4/botx/notifications/direct/sync."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={"sync_id": "sid-sync"})

        client = _make_client(bot_config, handler)
        sync_id = await client.send_message(
            BotxMessage(group_chat_id="chat-1", body="hi"), sync=True
        )
        assert sync_id == "sid-sync"
        assert captured["path"] == "/api/v4/botx/notifications/direct/sync"

    async def test_send_message_with_buttons_and_mentions(
        self, bot_config: BotConfig
    ) -> None:
        """Bubble/keyboard кнопки и mentions сериализуются в payload."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"result": {"sync_id": "x"}})

        client = _make_client(bot_config, handler)
        msg = BotxMessage(
            group_chat_id="c1",
            body="hi @{mention:m1}",
            bubble=[[BotxButton(command="/y", label="Yes")]],
            keyboard=[[BotxButton(command="/n", label="No")]],
            mentions=[BotxMention(mention_type="user", mention_id="m1", user_huid="u1", name="Alice")],
        )
        await client.send_message(msg)
        notif = captured["json"]["notification"]
        assert notif["bubble"][0][0]["command"] == "/y"
        assert notif["keyboard"][0][0]["label"] == "No"
        assert notif["mentions"][0]["mention_type"] == "user"
        assert notif["mentions"][0]["mention_data"]["user_huid"] == "u1"

    async def test_send_message_raises_on_http_error(self, bot_config: BotConfig) -> None:
        """HTTP 4xx → ``HTTPStatusError``."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "bad request"})

        client = _make_client(bot_config, handler)
        with pytest.raises(httpx.HTTPStatusError):
            await client.send_message(BotxMessage(group_chat_id="c1", body="x"))


# ── reply / edit / delete ───────────────────────────────────────────────


class TestReplyEditDelete:
    """Тесты reply/edit/delete сообщений."""

    async def test_reply_includes_source_sync_id(self, bot_config: BotConfig) -> None:
        """Reply payload содержит ``source_sync_id``."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"result": {"sync_id": "reply-1"}})

        client = _make_client(bot_config, handler)
        sync_id = await client.reply(
            "src-1", BotxMessage(group_chat_id="c1", body="re: ok")
        )
        assert sync_id == "reply-1"
        assert captured["path"] == "/api/v3/botx/events/reply_event"
        assert captured["json"]["source_sync_id"] == "src-1"

    async def test_edit_message_only_passed_fields(self, bot_config: BotConfig) -> None:
        """Edit payload содержит только переданные поля в ``result``."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={})

        client = _make_client(bot_config, handler)
        await client.edit_message(
            "sid-1",
            body="updated",
            bubble=[],
            status="ok",
            ignored="should-not-appear",
        )
        body = captured["json"]
        assert captured["path"] == "/api/v3/botx/events/edit_event"
        assert body["sync_id"] == "sid-1"
        assert body["result"]["body"] == "updated"
        assert body["result"]["bubble"] == []
        assert body["result"]["status"] == "ok"
        assert "ignored" not in body["result"]
        assert "keyboard" not in body["result"]

    async def test_delete_message(self, bot_config: BotConfig) -> None:
        """Delete отправляет sync_id и group_chat_id."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={})

        client = _make_client(bot_config, handler)
        await client.delete_message("sid-9", "chat-9")
        assert captured["path"] == "/api/v3/botx/events/delete_event"
        assert captured["json"] == {"sync_id": "sid-9", "group_chat_id": "chat-9"}


# ── typing / event_status ───────────────────────────────────────────────


class TestTypingAndStatus:
    """Тесты typing-индикаторов и event_status."""

    async def test_send_typing(self, bot_config: BotConfig) -> None:
        """``send_typing`` → POST /api/v3/botx/events/typing."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={})

        client = _make_client(bot_config, handler)
        await client.send_typing("chat-77")
        assert captured["path"] == "/api/v3/botx/events/typing"
        assert captured["json"] == {"group_chat_id": "chat-77"}

    async def test_stop_typing(self, bot_config: BotConfig) -> None:
        """``stop_typing`` → POST /api/v3/botx/events/stop_typing."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            return httpx.Response(200, json={})

        client = _make_client(bot_config, handler)
        await client.stop_typing("c1")
        assert captured["path"] == "/api/v3/botx/events/stop_typing"

    async def test_get_event_status(self, bot_config: BotConfig) -> None:
        """``get_event_status`` шлёт GET с ``sync_id`` query-параметром."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["query"] = dict(request.url.params)
            return httpx.Response(
                200,
                json={"result": {"group_chat_id": "c1", "sent_to": ["u1"]}},
            )

        client = _make_client(bot_config, handler)
        result = await client.get_event_status("sid-X")
        assert captured["method"] == "GET"
        assert captured["path"] == "/api/v3/botx/events/event_status"
        assert captured["query"] == {"sync_id": "sid-X"}
        assert result["result"]["group_chat_id"] == "c1"


# ── upload_file ─────────────────────────────────────────────────────────


class TestUploadFile:
    """Тесты multipart-загрузки файлов."""

    async def test_upload_file_multipart(self, bot_config: BotConfig) -> None:
        """``upload_file`` отправляет multipart с meta и content."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["method"] = request.method
            captured["path"] = request.url.path
            captured["content_type"] = request.headers.get("content-type", "")
            captured["body"] = request.content
            return httpx.Response(
                200,
                json={"result": {"file_id": "f1", "file_url": "/files/f1"}},
            )

        client = _make_client(bot_config, handler)
        result = await client.upload_file(b"hello-bytes", "file.txt", "chat-7")
        assert captured["method"] == "POST"
        assert captured["path"] == "/api/v3/botx/files/upload"
        assert captured["content_type"].startswith("multipart/form-data")
        # meta форма + content форма попадают в multipart-body
        assert b"chat-7" in captured["body"]
        assert b"hello-bytes" in captured["body"]
        assert result["result"]["file_id"] == "f1"


# ── internal_notification / chat / members / search_user ─────────────────


class TestExtraEndpoints:
    """Тесты дополнительных endpoints."""

    async def test_send_internal_notification(self, bot_config: BotConfig) -> None:
        """Internal notification → /api/v4/botx/notifications/internal."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["path"] = request.url.path
            captured["json"] = json.loads(request.content)
            return httpx.Response(200, json={"result": {"sync_id": "int-1"}})

        client = _make_client(bot_config, handler)
        sync_id = await client.send_internal_notification(
            "chat-1", {"k": "v"}, recipients=["bot-2"]
        )
        assert sync_id == "int-1"
        assert captured["path"] == "/api/v4/botx/notifications/internal"
        assert captured["json"]["data"] == {"k": "v"}
        assert captured["json"]["opts"]["recipients"] == ["bot-2"]

    async def test_get_chat_info(self, bot_config: BotConfig) -> None:
        """``get_chat_info`` → GET /api/v3/botx/chats/info?group_chat_id=..."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = dict(request.url.params)
            return httpx.Response(200, json={"result": {"name": "test chat"}})

        client = _make_client(bot_config, handler)
        info = await client.get_chat_info("c1")
        assert captured["query"] == {"group_chat_id": "c1"}
        assert info["result"]["name"] == "test chat"

    async def test_get_members_returns_list(self, bot_config: BotConfig) -> None:
        """``get_members`` достаёт список из ``result``."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"result": [{"user_huid": "u1"}, {"user_huid": "u2"}]}
            )

        client = _make_client(bot_config, handler)
        members = await client.get_members("c1")
        assert len(members) == 2
        assert members[0]["user_huid"] == "u1"

    async def test_search_user_by_email(self, bot_config: BotConfig) -> None:
        """Поиск по email — успешный сценарий."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured["query"] = dict(request.url.params)
            return httpx.Response(
                200, json={"result": {"user_huid": "u1", "email": "a@b"}}
            )

        client = _make_client(bot_config, handler)
        user = await client.search_user(email="a@b")
        assert captured["query"] == {"email": "a@b"}
        assert user is not None
        assert user["user_huid"] == "u1"

    async def test_search_user_404_returns_none(self, bot_config: BotConfig) -> None:
        """404 от BotX → ``None`` (не исключение)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "not found"})

        client = _make_client(bot_config, handler)
        user = await client.search_user(huid="missing")
        assert user is None

    async def test_search_user_requires_email_or_huid(
        self, bot_config: BotConfig
    ) -> None:
        """Без email/huid — ``ValueError``."""
        client = ExpressBotClient(bot_config)
        with pytest.raises(ValueError, match="email или huid"):
            await client.search_user()


# ── Контекст-менеджер ────────────────────────────────────────────────────


class TestContextManager:
    """Тесты ``async with`` open/close семантики."""

    async def test_context_manager_lifecycle(self, bot_config: BotConfig) -> None:
        """``async with`` создаёт и закрывает HTTP-клиент."""
        client = ExpressBotClient(bot_config)
        assert client._http is None  # noqa: SLF001
        async with client as opened:
            assert opened is client
            assert client._http is not None  # noqa: SLF001
        assert client._http is None  # noqa: SLF001

    def test_http_property_lazy_init(self, bot_config: BotConfig) -> None:
        """``client.http`` создаёт временный AsyncClient если не открыт."""
        client = ExpressBotClient(bot_config)
        http = client.http
        assert isinstance(http, httpx.AsyncClient)
        # повторный вызов — тот же экземпляр
        assert client.http is http
