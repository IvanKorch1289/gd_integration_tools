"""Unit-тесты для DSL Express-процессоров (Wave 11 expansion).

Покрытие 7 процессоров:
    * ``ExpressSendProcessor``
    * ``ExpressReplyProcessor``
    * ``ExpressEditProcessor``
    * ``ExpressTypingProcessor``
    * ``ExpressSendFileProcessor``
    * ``ExpressMentionProcessor``
    * ``ExpressStatusProcessor``

Подход:
    * ``get_express_client`` подменяется фабрикой ``FakeBotClient`` (AsyncMock-методы).
    * ``log_outgoing_message`` подменяется no-op AsyncMock — Mongo не нужен.
    * ``s3_client.get_object_bytes`` — MagicMock c AsyncMock.
    * Используются реальные ``Exchange`` и ``ExecutionContext``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.processors.express import (
    ExpressEditProcessor,
    ExpressMentionProcessor,
    ExpressReplyProcessor,
    ExpressSendFileProcessor,
    ExpressSendProcessor,
    ExpressStatusProcessor,
    ExpressTypingProcessor,
)
from src.infrastructure.clients.external.express_bot import BotxMention

# ── Хелперы ──────────────────────────────────────────────────────────────


class FakeBotClient:
    """In-memory заглушка ``ExpressBotClient`` с async context-manager.

    Все BotX-методы — AsyncMock с конфигурируемым возвратом. Поддерживает
    ``async with client:`` для совместимости с реальным API.
    """

    def __init__(
        self,
        *,
        send_result: str = "sync-1",
        reply_result: str = "reply-1",
        upload_result: dict[str, Any] | None = None,
        status_result: dict[str, Any] | None = None,
    ) -> None:
        self.send_message = AsyncMock(return_value=send_result)
        self.reply = AsyncMock(return_value=reply_result)
        self.edit_message = AsyncMock(return_value=None)
        self.send_typing = AsyncMock(return_value=None)
        self.stop_typing = AsyncMock(return_value=None)
        self.upload_file = AsyncMock(
            return_value=upload_result or {"result": {"file_id": "f1", "file_url": "/u/f1"}}
        )
        self.get_event_status = AsyncMock(
            return_value=status_result
            or {"result": {"group_chat_id": "c1", "sent_to": ["u1"]}}
        )

    async def __aenter__(self) -> FakeBotClient:
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
def fake_client() -> FakeBotClient:
    """Дефолтный fake-клиент для unit-тестов."""
    return FakeBotClient()


@pytest.fixture(autouse=True)
def _patch_log_outgoing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Глушим Mongo-логирование во всех Express-процессорах (best-effort).

    ``log_outgoing_message`` сам гасит исключения, но без подмены он
    каждый раз пытается импортировать MongoDB-инфраструктуру.
    """
    noop = AsyncMock(return_value=None)
    for module_name in (
        "src.dsl.engine.processors.express.send",
        "src.dsl.engine.processors.express.reply",
        "src.dsl.engine.processors.express.send_file",
    ):
        monkeypatch.setattr(f"{module_name}.log_outgoing_message", noop, raising=True)


def _install_client(
    monkeypatch: pytest.MonkeyPatch, module: str, client: FakeBotClient
) -> None:
    """Подменяет ``get_express_client`` в модуле процессора на возврат ``client``."""
    monkeypatch.setattr(
        f"src.dsl.engine.processors.express.{module}.get_express_client",
        lambda bot_name="main_bot": client,
        raising=True,
    )


# ── ExpressSendProcessor ─────────────────────────────────────────────────


class TestExpressSendProcessor:
    """Тесты для ExpressSendProcessor."""

    def test_requires_body_or_body_from(self) -> None:
        """Без body/body_from — ValueError."""
        with pytest.raises(ValueError, match="body или body_from"):
            ExpressSendProcessor()

    def test_to_spec_round_trip(self) -> None:
        """``to_spec()`` возвращает валидный YAML-spec."""
        proc = ExpressSendProcessor(
            bot="main_bot",
            chat_id_from="body.chat_id",
            body="hi",
            bubble=[[{"command": "/y", "label": "Yes"}]],
            sync=True,
        )
        spec = proc.to_spec()
        assert "express_send" in spec
        payload = spec["express_send"]
        assert payload["bot"] == "main_bot"
        assert payload["body"] == "hi"
        assert payload["sync"] is True
        assert payload["bubble"] == [[{"command": "/y", "label": "Yes"}]]

    async def test_send_static_body_async(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Статический body отправляется через ``send_message``."""
        _install_client(monkeypatch, "send", fake_client)
        proc = ExpressSendProcessor(body="hello", chat_id_from="body.chat_id")
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        fake_client.send_message.assert_awaited_once()
        msg_arg = fake_client.send_message.await_args.args[0]
        assert msg_arg.group_chat_id == "c1"
        assert msg_arg.body == "hello"
        assert exchange.get_property("express_sync_id") == "sync-1"

    async def test_send_dynamic_body_from_property(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """``body_from`` извлекается из ``properties``."""
        _install_client(monkeypatch, "send", fake_client)
        proc = ExpressSendProcessor(
            chat_id_from="body.chat_id", body_from="properties.text"
        )
        exchange = _make_exchange(body={"chat_id": "c2"})
        exchange.set_property("text", "dynamic")

        await proc.process(exchange, _make_context())

        msg_arg = fake_client.send_message.await_args.args[0]
        assert msg_arg.body == "dynamic"

    async def test_send_missing_chat_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Если chat_id не извлекается — exchange.fail."""
        _install_client(monkeypatch, "send", fake_client)
        proc = ExpressSendProcessor(body="hi")
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed
        assert exchange.error is not None
        assert "chat_id" in exchange.error
        fake_client.send_message.assert_not_awaited()

    async def test_send_handles_client_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Исключение клиента → пишется ``*_error`` property."""
        _install_client(monkeypatch, "send", fake_client)
        fake_client.send_message.side_effect = RuntimeError("boom")
        proc = ExpressSendProcessor(body="hi", chat_id_from="body.chat_id")
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        assert exchange.get_property("express_sync_id_error") == "boom"

    async def test_send_with_buttons(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Bubble и keyboard сериализуются в BotxButton."""
        _install_client(monkeypatch, "send", fake_client)
        proc = ExpressSendProcessor(
            body="pick",
            chat_id_from="body.chat_id",
            bubble=[[{"command": "/yes", "label": "Yes"}]],
            keyboard=[[{"command": "/no", "label": "No"}]],
        )
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        msg_arg = fake_client.send_message.await_args.args[0]
        assert len(msg_arg.bubble) == 1 and msg_arg.bubble[0][0].command == "/yes"
        assert len(msg_arg.keyboard) == 1 and msg_arg.keyboard[0][0].command == "/no"


# ── ExpressReplyProcessor ────────────────────────────────────────────────


class TestExpressReplyProcessor:
    """Тесты для ExpressReplyProcessor."""

    def test_requires_body_or_body_from(self) -> None:
        """Без body/body_from — ValueError."""
        with pytest.raises(ValueError, match="body или body_from"):
            ExpressReplyProcessor()

    def test_to_spec(self) -> None:
        proc = ExpressReplyProcessor(body="re")
        spec = proc.to_spec()
        assert "express_reply" in spec
        assert spec["express_reply"]["body"] == "re"

    async def test_reply_sends_with_source_sync_id(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Reply вызывает ``client.reply`` с source_sync_id."""
        _install_client(monkeypatch, "reply", fake_client)
        proc = ExpressReplyProcessor(
            body="re", chat_id_from="body.chat_id"
        )
        exchange = _make_exchange(
            body={"chat_id": "c1"},
            headers={"X-Express-Sync-Id": "src-7"},
        )

        await proc.process(exchange, _make_context())

        fake_client.reply.assert_awaited_once()
        args = fake_client.reply.await_args.args
        assert args[0] == "src-7"
        assert args[1].body == "re"
        assert exchange.get_property("express_reply_sync_id") == "reply-1"

    async def test_reply_missing_source_sync_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Без source_sync_id — exchange.fail."""
        _install_client(monkeypatch, "reply", fake_client)
        proc = ExpressReplyProcessor(body="re")
        exchange = _make_exchange(body={"group_chat_id": "c1"})

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed
        assert "source_sync_id" in (exchange.error or "")

    async def test_reply_missing_chat_id_or_text_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Если chat_id извлечён но текст пуст — exchange.fail."""
        _install_client(monkeypatch, "reply", fake_client)
        proc = ExpressReplyProcessor(
            body_from="properties.missing", chat_id_from="body.chat_id"
        )
        exchange = _make_exchange(
            body={"chat_id": "c1"},
            headers={"X-Express-Sync-Id": "src-7"},
        )

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed


# ── ExpressEditProcessor ─────────────────────────────────────────────────


class TestExpressEditProcessor:
    """Тесты для ExpressEditProcessor."""

    def test_to_spec_minimal(self) -> None:
        spec = ExpressEditProcessor().to_spec()
        assert "express_edit" in spec

    async def test_edit_calls_edit_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """``edit_message`` вызывается с переданными полями."""
        _install_client(monkeypatch, "edit", fake_client)
        proc = ExpressEditProcessor(body="updated", bubble=[])
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        fake_client.edit_message.assert_awaited_once()
        args = fake_client.edit_message.await_args
        assert args.args[0] == "sid-1"
        assert args.kwargs["body"] == "updated"
        assert args.kwargs["bubble"] == []

    async def test_edit_skips_when_no_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Если ничего не передано — edit пропускается."""
        _install_client(monkeypatch, "edit", fake_client)
        proc = ExpressEditProcessor()
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        fake_client.edit_message.assert_not_awaited()

    async def test_edit_missing_sync_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Без sync_id — exchange.fail."""
        _install_client(monkeypatch, "edit", fake_client)
        proc = ExpressEditProcessor(body="x")
        exchange = _make_exchange()

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed

    async def test_edit_handles_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Исключение → пишется express_edit_error."""
        _install_client(monkeypatch, "edit", fake_client)
        fake_client.edit_message.side_effect = RuntimeError("nope")
        proc = ExpressEditProcessor(body="x")
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        assert exchange.get_property("express_edit_error") == "nope"


# ── ExpressTypingProcessor ───────────────────────────────────────────────


class TestExpressTypingProcessor:
    """Тесты для ExpressTypingProcessor."""

    def test_invalid_action_raises(self) -> None:
        """Неизвестный action → ValueError."""
        with pytest.raises(ValueError, match="action"):
            ExpressTypingProcessor(action="invalid")

    def test_to_spec(self) -> None:
        spec = ExpressTypingProcessor(action="stop").to_spec()
        assert spec["express_typing"]["action"] == "stop"

    async def test_typing_start(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """action=start → send_typing."""
        _install_client(monkeypatch, "typing", fake_client)
        proc = ExpressTypingProcessor(action="start")
        exchange = _make_exchange(body={"group_chat_id": "c1"})

        await proc.process(exchange, _make_context())

        fake_client.send_typing.assert_awaited_once_with("c1")
        fake_client.stop_typing.assert_not_awaited()

    async def test_typing_stop(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """action=stop → stop_typing."""
        _install_client(monkeypatch, "typing", fake_client)
        proc = ExpressTypingProcessor(action="stop")
        exchange = _make_exchange(body={"group_chat_id": "c2"})

        await proc.process(exchange, _make_context())

        fake_client.stop_typing.assert_awaited_once_with("c2")
        fake_client.send_typing.assert_not_awaited()

    async def test_typing_no_chat_id_silent_skip(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Без chat_id — тихий skip (не fail)."""
        _install_client(monkeypatch, "typing", fake_client)
        proc = ExpressTypingProcessor(action="start")
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        fake_client.send_typing.assert_not_awaited()
        # status НЕ должен меняться на failed для typing
        assert exchange.status != ExchangeStatus.failed


# ── ExpressSendFileProcessor ─────────────────────────────────────────────


class TestExpressSendFileProcessor:
    """Тесты для ExpressSendFileProcessor."""

    def test_requires_source(self) -> None:
        """Без s3_key_from/file_data_property — ValueError."""
        with pytest.raises(ValueError, match="s3_key_from или file_data_property"):
            ExpressSendFileProcessor(file_name="x.txt")

    def test_requires_file_name(self) -> None:
        """Без file_name/file_name_from — ValueError."""
        with pytest.raises(ValueError, match="file_name"):
            ExpressSendFileProcessor(file_data_property="data")

    def test_to_spec(self) -> None:
        spec = ExpressSendFileProcessor(
            file_data_property="data", file_name="a.txt"
        ).to_spec()
        assert "express_send_file" in spec
        assert spec["express_send_file"]["file_name"] == "a.txt"

    async def test_send_from_property_bytes(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Файл из exchange-property → upload + send."""
        _install_client(monkeypatch, "send_file", fake_client)
        proc = ExpressSendFileProcessor(
            chat_id_from="body.chat_id",
            file_data_property="payload",
            file_name="report.pdf",
            body="here",
        )
        exchange = _make_exchange(body={"chat_id": "c1"})
        exchange.set_property("payload", b"PDF-bytes")

        await proc.process(exchange, _make_context())

        fake_client.upload_file.assert_awaited_once()
        upload_kwargs = fake_client.upload_file.await_args.kwargs
        assert upload_kwargs["file_data"] == b"PDF-bytes"
        assert upload_kwargs["file_name"] == "report.pdf"
        fake_client.send_message.assert_awaited_once()
        msg_arg = fake_client.send_message.await_args.args[0]
        assert msg_arg.body == "here"
        assert msg_arg.file == {"file_id": "f1", "file_url": "/u/f1"}
        assert exchange.get_property("express_file_sync_id") == "sync-1"

    async def test_send_from_property_str(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Строка в property конвертируется в bytes (utf-8)."""
        _install_client(monkeypatch, "send_file", fake_client)
        proc = ExpressSendFileProcessor(
            chat_id_from="body.chat_id",
            file_data_property="payload",
            file_name="text.txt",
        )
        exchange = _make_exchange(body={"chat_id": "c1"})
        exchange.set_property("payload", "abc")

        await proc.process(exchange, _make_context())

        upload_kwargs = fake_client.upload_file.await_args.kwargs
        assert upload_kwargs["file_data"] == b"abc"

    async def test_send_from_s3(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Файл из S3 — приоритетный источник.

        Используем ``sys.modules`` injection вместо ``monkeypatch.setattr``,
        потому что ``s3_pool`` тянет ``botocore``, который может быть не
        установлен в тестовом окружении.
        """
        import sys
        import types

        _install_client(monkeypatch, "send_file", fake_client)
        fake_s3 = MagicMock()
        fake_s3.get_object_bytes = AsyncMock(return_value=b"S3-DATA")
        fake_module = types.ModuleType(
            "src.infrastructure.clients.storage.s3_pool"
        )
        fake_module.s3_client = fake_s3  # type: ignore[attr-defined]
        monkeypatch.setitem(
            sys.modules, "src.infrastructure.clients.storage.s3_pool", fake_module
        )

        proc = ExpressSendFileProcessor(
            chat_id_from="body.chat_id",
            s3_key_from="body.s3_key",
            file_name="from_s3.bin",
        )
        exchange = _make_exchange(body={"chat_id": "c1", "s3_key": "k/file"})

        await proc.process(exchange, _make_context())

        fake_s3.get_object_bytes.assert_awaited_once_with("k/file")
        assert fake_client.upload_file.await_args.kwargs["file_data"] == b"S3-DATA"

    async def test_send_no_chat_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Без chat_id — exchange.fail."""
        _install_client(monkeypatch, "send_file", fake_client)
        proc = ExpressSendFileProcessor(
            file_data_property="payload",
            file_name="a.bin",
        )
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed

    async def test_send_no_file_data_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Если данных файла нет — exchange.fail."""
        _install_client(monkeypatch, "send_file", fake_client)
        proc = ExpressSendFileProcessor(
            chat_id_from="body.chat_id",
            file_data_property="missing",
            file_name="a.bin",
        )
        exchange = _make_exchange(body={"chat_id": "c1"})

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed


# ── ExpressMentionProcessor ──────────────────────────────────────────────


class TestExpressMentionProcessor:
    """Тесты для ExpressMentionProcessor."""

    def test_invalid_mention_type(self) -> None:
        """Неверный тип → ValueError."""
        with pytest.raises(ValueError, match="mention_type"):
            ExpressMentionProcessor(mention_type="invalid", target_from="body.x")

    def test_target_required_for_user(self) -> None:
        """target_from обязателен для не-all типов."""
        with pytest.raises(ValueError, match="target_from"):
            ExpressMentionProcessor(mention_type="user")

    def test_to_spec(self) -> None:
        spec = ExpressMentionProcessor(
            mention_type="user", target_from="body.huid"
        ).to_spec()
        assert "express_mention" in spec
        assert spec["express_mention"]["mention_type"] == "user"

    async def test_mention_user_appends_to_property(self) -> None:
        """user mention заполняет user_huid."""
        proc = ExpressMentionProcessor(
            mention_type="user",
            target_from="body.user_huid",
            name_from="body.user_name",
        )
        exchange = _make_exchange(body={"user_huid": "u1", "user_name": "Alice"})

        await proc.process(exchange, _make_context())

        mentions = exchange.get_property("express_mentions")
        assert isinstance(mentions, list) and len(mentions) == 1
        m = mentions[0]
        assert isinstance(m, BotxMention)
        assert m.mention_type == "user"
        assert m.user_huid == "u1"
        assert m.name == "Alice"
        assert m.group_chat_id is None

    async def test_mention_chat_uses_group_chat_id(self) -> None:
        """chat mention заполняет group_chat_id, не user_huid."""
        proc = ExpressMentionProcessor(
            mention_type="chat", target_from="body.chat_id"
        )
        exchange = _make_exchange(body={"chat_id": "c-99"})

        await proc.process(exchange, _make_context())

        mentions = exchange.get_property("express_mentions")
        assert mentions[0].group_chat_id == "c-99"
        assert mentions[0].user_huid is None

    async def test_mention_all_no_target_required(self) -> None:
        """mention_type=all не требует target_from."""
        proc = ExpressMentionProcessor(mention_type="all")
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        mentions = exchange.get_property("express_mentions")
        assert len(mentions) == 1
        assert mentions[0].mention_type == "all"

    async def test_mention_appends_to_existing_list(self) -> None:
        """Повторный вызов добавляет mention в существующий список."""
        proc = ExpressMentionProcessor(
            mention_type="user", target_from="body.huid"
        )
        exchange = _make_exchange(body={"huid": "u1"})

        await proc.process(exchange, _make_context())
        await proc.process(exchange, _make_context())

        mentions = exchange.get_property("express_mentions")
        assert len(mentions) == 2

    async def test_mention_uses_provided_id(self) -> None:
        """Если ``mention_id`` задан — он используется (не uuid4)."""
        proc = ExpressMentionProcessor(
            mention_type="user",
            target_from="body.huid",
            mention_id="fixed-id",
        )
        exchange = _make_exchange(body={"huid": "u1"})

        await proc.process(exchange, _make_context())

        mentions = exchange.get_property("express_mentions")
        assert mentions[0].mention_id == "fixed-id"

    async def test_mention_empty_target_skips(self) -> None:
        """Пустой target для user — silently skipped."""
        proc = ExpressMentionProcessor(
            mention_type="user", target_from="body.huid"
        )
        exchange = _make_exchange(body={})

        await proc.process(exchange, _make_context())

        # Ничего не записано
        assert exchange.get_property("express_mentions") is None


# ── ExpressStatusProcessor ───────────────────────────────────────────────


class TestExpressStatusProcessor:
    """Тесты для ExpressStatusProcessor."""

    def test_to_spec(self) -> None:
        spec = ExpressStatusProcessor().to_spec()
        assert "express_status" in spec

    async def test_status_writes_payload(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """``get_event_status`` → payload в property."""
        _install_client(monkeypatch, "status", fake_client)
        proc = ExpressStatusProcessor()
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        fake_client.get_event_status.assert_awaited_once_with("sid-1")
        payload = exchange.get_property("express_event_status")
        assert payload == {"group_chat_id": "c1", "sent_to": ["u1"]}

    async def test_status_unwraps_result_key(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Если ответ {result: X} — записывается X (не весь wrapper)."""
        client = FakeBotClient(status_result={"result": {"sent_to": ["u9"]}})
        _install_client(monkeypatch, "status", client)
        proc = ExpressStatusProcessor()
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        assert exchange.get_property("express_event_status") == {"sent_to": ["u9"]}

    async def test_status_missing_sync_id_fails(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Без sync_id — exchange.fail."""
        _install_client(monkeypatch, "status", fake_client)
        proc = ExpressStatusProcessor()
        exchange = _make_exchange()

        await proc.process(exchange, _make_context())

        assert exchange.status == ExchangeStatus.failed

    async def test_status_handles_exception(
        self,
        monkeypatch: pytest.MonkeyPatch,
        fake_client: FakeBotClient,
    ) -> None:
        """Исключение клиента → пишется *_error property."""
        _install_client(monkeypatch, "status", fake_client)
        fake_client.get_event_status.side_effect = RuntimeError("api-down")
        proc = ExpressStatusProcessor()
        exchange = _make_exchange()
        exchange.set_property("express_sync_id", "sid-1")

        await proc.process(exchange, _make_context())

        assert exchange.get_property("express_event_status_error") == "api-down"
