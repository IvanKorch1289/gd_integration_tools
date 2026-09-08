"""Tests for src.backend.dsl.engine.processors.express.reply.

T3 coverage sprint cycle 6: тесты для ``ExpressReplyProcessor.__init__``
(validation) и ``process()`` (reply via BotxMessage).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express.reply import ExpressReplyProcessor


def _make_exchange(properties: dict | None = None) -> tuple[Exchange, dict]:
    """Exchange stub with captured properties/fail."""
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
    """Both body=None and body_from=None raises ValueError."""
    with pytest.raises(ValueError, match="укажите body или body_from"):
        ExpressReplyProcessor()


def test_init_with_static_body_ok() -> None:
    proc = ExpressReplyProcessor(body="static text")
    assert proc._body == "static text"
    assert proc._body_from is None


def test_init_with_body_from_ok() -> None:
    proc = ExpressReplyProcessor(body_from="body.text")
    assert proc._body is None
    assert proc._body_from == "body.text"


def test_init_defaults() -> None:
    proc = ExpressReplyProcessor(body="x")
    assert proc._bot == "main_bot"
    assert proc._source_sync_id_from == "header.X-Express-Sync-Id"
    assert proc._chat_id_from == "body.group_chat_id"
    assert proc._result_property == "express_reply_sync_id"


def test_init_custom_result_property() -> None:
    proc = ExpressReplyProcessor(body="x", result_property="custom_reply_id")
    assert proc._result_property == "custom_reply_id"


def test_to_spec_minimal() -> None:
    proc = ExpressReplyProcessor(body="hello")
    spec = proc.to_spec()
    assert spec == {
        "express_reply": {
            "bot": "main_bot",
            "source_sync_id_from": "header.X-Express-Sync-Id",
            "chat_id_from": "body.group_chat_id",
            "result_property": "express_reply_sync_id",
            "body": "hello",
        }
    }


def test_to_spec_with_body_from() -> None:
    proc = ExpressReplyProcessor(body_from="properties.msg")
    spec = proc.to_spec()
    assert spec["express_reply"]["body_from"] == "properties.msg"
    assert "body" not in spec["express_reply"]


# ─────────── process() ───────────


class _FakeBotxMessage:
    """Matches BotxMessage contract (positional or kw)."""

    def __init__(self, group_chat_id: str, body: str) -> None:
        self.group_chat_id = group_chat_id
        self.body = body


class _FakeClient:
    """Async context manager + reply stub."""

    def __init__(self, reply_id: str = "reply-sync-001") -> None:
        self.reply_calls: list[tuple[str, object]] = []
        self.reply_id = reply_id

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def reply(self, source_sync_id: str, msg: object) -> str:
        self.reply_calls.append((source_sync_id, msg))
        return self.reply_id


@pytest.mark.asyncio
async def test_process_sends_reply_and_stores_sync_id() -> None:
    """Static body → reply sent, sync_id stored in result_property."""
    proc = ExpressReplyProcessor(body="hello reply")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient(reply_id="reply-sync-XYZ")
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: {
            "header.X-Express-Sync-Id": "src-001",
            "body.group_chat_id": "chat-1",
            "body.text": None,
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.reply_calls) == 1
    sync_id_arg, msg_arg = fake_client.reply_calls[0]
    assert sync_id_arg == "src-001"
    assert msg_arg.body == "hello reply"
    assert msg_arg.group_chat_id == "chat-1"
    assert captured["express_reply_sync_id"] == "reply-sync-XYZ"


@pytest.mark.asyncio
async def test_process_uses_body_from_when_body_none() -> None:
    """body_from path — uses dynamic text from exchange."""
    proc = ExpressReplyProcessor(body_from="properties.text")
    ex, captured = _make_exchange(properties={"text": "dynamic text"})

    fake_client = _FakeClient(reply_id="reply-1")
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: {
            "header.X-Express-Sync-Id": "src-1",
            "body.group_chat_id": "chat-1",
            "properties.text": "dynamic text",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    assert fake_client.reply_calls[0][1].body == "dynamic text"


@pytest.mark.asyncio
async def test_process_static_body_priority_over_body_from() -> None:
    """body (static) wins over body_from."""
    proc = ExpressReplyProcessor(body="STATIC", body_from="properties.txt")
    ex, _captured = _make_exchange(properties={"text": "DYNAMIC"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1",
    ):
        await proc.process(ex, _ctx())

    assert fake_client.reply_calls[0][1].body == "STATIC"


@pytest.mark.asyncio
async def test_process_skips_when_source_sync_id_missing() -> None:
    """source_sync_id_from resolves to None → exchange.fail, ранний return."""
    proc = ExpressReplyProcessor(body="text")
    ex, captured = _make_exchange()

    with patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        return_value=None,
    ):
        await proc.process(ex, _ctx())

    assert "source_sync_id отсутствует" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_text_empty() -> None:
    """text is None or empty → exchange.fail."""
    proc = ExpressReplyProcessor(body="placeholder")  # validation passes
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    with patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: {
            "header.X-Express-Sync-Id": "src-1",
            "body.group_chat_id": "chat-1",
            "": None,
        }.get(expr),
    ):
        # Override body to None through body_from path
        proc._body = None
        proc._body_from = ""  # resolves to None
        await proc.process(ex, _ctx())

    assert "chat_id или текст пусты" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing() -> None:
    proc = ExpressReplyProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": None})

    with patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else None,
    ):
        await proc.process(ex, _ctx())

    assert "chat_id или текст пусты" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_client_none_skips_silently() -> None:
    """get_express_client returns None → graceful no-op (no fail, no error)."""
    proc = ExpressReplyProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=None,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    # No error recorded, no sync_id stored
    assert "express_reply_sync_id" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_client_exception_records_error() -> None:
    """Если reply raises → records ``{result_property}_error``."""
    proc = ExpressReplyProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.reply = AsyncMock(side_effect=RuntimeError("BotX 503"))

    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=error_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("express_reply_sync_id_error") == "BotX 503"


@pytest.mark.asyncio
async def test_process_source_sync_id_coerced_to_str() -> None:
    """source_sync_id всегда приводится к str перед отправке в client."""
    proc = ExpressReplyProcessor(body="text")
    ex, _captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: 12345 if expr == "header.X-Express-Sync-Id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    sync_id_arg = fake_client.reply_calls[0][0]
    assert sync_id_arg == "12345"
    assert isinstance(sync_id_arg, str)


@pytest.mark.asyncio
async def test_process_chat_id_coerced_to_str() -> None:
    proc = ExpressReplyProcessor(body="text")
    ex, _captured = _make_exchange()

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else 9999,
    ):
        await proc.process(ex, _ctx())

    msg_arg = fake_client.reply_calls[0][1]
    assert msg_arg.group_chat_id == "9999"
    assert isinstance(msg_arg.group_chat_id, str)


@pytest.mark.asyncio
async def test_process_default_result_property_customizable() -> None:
    proc = ExpressReplyProcessor(
        body="text",
        result_property="custom_reply_id",
    )
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient(reply_id="r-123")
    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("custom_reply_id") == "r-123"


@pytest.mark.asyncio
async def test_process_exception_uses_custom_result_property_error_key() -> None:
    proc = ExpressReplyProcessor(
        body="text",
        result_property="custom_id",
    )
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.reply = AsyncMock(side_effect=RuntimeError("timeout"))

    with patch(
        "src.backend.dsl.engine.processors.express.reply.get_express_client",
        return_value=error_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(BotxMessage=_FakeBotxMessage),
    ), patch(
        "src.backend.dsl.engine.processors.express.reply.resolve_value",
        lambda exch, expr: "src-1" if expr == "header.X-Express-Sync-Id" else "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("custom_id_error") == "timeout"
