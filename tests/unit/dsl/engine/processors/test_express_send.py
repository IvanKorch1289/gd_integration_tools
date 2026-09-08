"""Tests for src.backend.dsl.engine.processors.express.send.

T3 coverage sprint cycle 7: тесты для ``ExpressSendProcessor.__init__``,
``_normalize_btn`` (static helper), ``process()`` (BotxMessage construction +
send_message call + metrics recording), ``to_spec``.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express.send import ExpressSendProcessor


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


# ─────────── __init__ ───────────


def test_init_requires_body_or_body_from() -> None:
    with pytest.raises(ValueError, match="укажите body или body_from"):
        ExpressSendProcessor()


def test_init_with_static_body() -> None:
    proc = ExpressSendProcessor(body="text")
    assert proc._body == "text"
    assert proc._body_from is None
    assert proc._bubble == []
    assert proc._keyboard == []
    assert proc._status == "ok"
    assert proc._silent_response is False
    assert proc._sync is False


def test_init_with_bubble_keyboard_normalized() -> None:
    proc = ExpressSendProcessor(
        body="x",
        bubble=[[{"command": "btn1", "label": "B1"}]],
        keyboard=[[{"command": "kb1", "label": "K1"}]],
    )
    assert proc._bubble == [[{"command": "btn1", "label": "B1"}]]
    assert proc._keyboard == [[{"command": "kb1", "label": "K1"}]]


def test_init_default_chat_id_from() -> None:
    proc = ExpressSendProcessor(body="x")
    assert proc._chat_id_from == "body.group_chat_id"


def test_init_defaults() -> None:
    proc = ExpressSendProcessor(body="x")
    assert proc._bot == "main_bot"
    assert proc._result_property == "express_sync_id"


def test_init_custom_sync() -> None:
    proc = ExpressSendProcessor(body="x", sync=True)
    assert proc._sync is True


def test_init_silent_response() -> None:
    proc = ExpressSendProcessor(body="x", silent_response=True)
    assert proc._silent_response is True


# ─────────── _normalize_btn ───────────


def test_normalize_btn_filters_allowed_keys() -> None:
    """Кнопка с неизвестными ключами → только allowed."""
    raw = {
        "command": "btn1",
        "label": "B1",
        "data": {"x": 1},
        "unknown_key": "should_be_filtered",
    }
    result = ExpressSendProcessor._normalize_btn(raw)
    assert result == {"command": "btn1", "label": "B1", "data": {"x": 1}}


def test_normalize_btn_all_allowed_keys() -> None:
    raw = {
        "command": "c",
        "label": "L",
        "data": {"k": "v"},
        "silent": True,
        "h_size": 2,
        "show_alert": True,
        "alert_text": "Alert",
        "font_color": "#FF0000",
        "background_color": "#00FF00",
        "align": "center",
    }
    result = ExpressSendProcessor._normalize_btn(raw)
    assert result == raw


def test_normalize_btn_no_allowed_keys() -> None:
    """Все ключи unknown → пустой dict."""
    raw = {"foo": "bar", "baz": 123}
    assert ExpressSendProcessor._normalize_btn(raw) == {}


def test_normalize_btn_empty_dict() -> None:
    assert ExpressSendProcessor._normalize_btn({}) == {}


# ─────────── process() ───────────


class _FakeBotxButton:
    """Match BotxButton.__init__ contract (kw)."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeBotxMessage:
    """Match BotxMessage __init__ contract."""

    def __init__(self, **kwargs: object) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _FakeClient:
    """Async context manager + send_message stub."""

    def __init__(self, sync_id: str = "sync-1") -> None:
        self.send_calls: list[tuple[object, bool]] = []
        self.sync_id = sync_id

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send_message(self, msg: object, sync: bool = False) -> str:
        self.send_calls.append((msg, sync))
        return self.sync_id


@pytest.mark.asyncio
async def test_process_sends_message_and_stores_sync_id() -> None:
    proc = ExpressSendProcessor(body="hello")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient(sync_id="sync-XYZ")
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.send_calls) == 1
    msg, sync = fake_client.send_calls[0]
    assert msg.body == "hello"
    assert msg.group_chat_id == "chat-1"
    assert msg.status == "ok"
    assert sync is False
    assert captured["express_sync_id"] == "sync-XYZ"


@pytest.mark.asyncio
async def test_process_sync_flag_passed() -> None:
    """sync=True → client.send_message(sync=True)."""
    proc = ExpressSendProcessor(body="text", sync=True)
    ex, _captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert fake_client.send_calls[0][1] is True


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing() -> None:
    proc = ExpressSendProcessor(body="text")
    ex, captured = _make_exchange()

    with patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        return_value=None,
    ):
        await proc.process(ex, _ctx())

    assert "не удалось извлечь chat_id" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_skips_when_text_empty() -> None:
    """body=None и body_from=None на runtime → exchange.fail."""
    proc = ExpressSendProcessor(body="placeholder")  # init ok
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    with patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1" if expr == "body.group_chat_id" else None,
    ):
        # Set body=None to force body_from=None path → resolve_value(None) → text empty
        proc._body = None
        proc._body_from = ""
        await proc.process(ex, _ctx())

    assert "текст сообщения пуст" in captured.get("__fail__", "")


@pytest.mark.asyncio
async def test_process_uses_body_from_when_body_none() -> None:
    proc = ExpressSendProcessor(body_from="properties.text")
    ex, _captured = _make_exchange(properties={"text": "from-exchange"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: {
            "body.group_chat_id": "chat-1",
            "properties.text": "from-exchange",
        }.get(expr),
    ):
        await proc.process(ex, _ctx())

    msg_arg = fake_client.send_calls[0][0]
    assert msg_arg.body == "from-exchange"


@pytest.mark.asyncio
async def test_process_static_body_priority_over_body_from() -> None:
    """body (static) wins."""
    proc = ExpressSendProcessor(body="STATIC", body_from="properties.text")
    ex, _captured = _make_exchange(properties={"text": "DYNAMIC"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert fake_client.send_calls[0][0].body == "STATIC"


@pytest.mark.asyncio
async def test_process_with_bubble_keyboard_builds_buttons() -> None:
    """bubble + keyboard конвертируются в BotxButton через _normalize_btn."""
    proc = ExpressSendProcessor(
        body="text",
        bubble=[[{"command": "btn1", "label": "B1", "unknown": "skip"}]],
        keyboard=[[{"command": "kb1", "label": "K1"}]],
    )
    ex, _captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient()
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    msg_arg = fake_client.send_calls[0][0]
    assert len(msg_arg.bubble) == 1
    assert len(msg_arg.bubble[0]) == 1
    assert msg_arg.bubble[0][0].command == "btn1"
    assert not hasattr(msg_arg.bubble[0][0], "unknown")  # filtered
    assert len(msg_arg.keyboard) == 1
    assert msg_arg.keyboard[0][0].command == "kb1"


@pytest.mark.asyncio
async def test_process_client_none_skips_silently() -> None:
    proc = ExpressSendProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=None,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert "express_sync_id" not in captured
    assert "__fail__" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error() -> None:
    """send_message raises → records ``{result_property}_error``."""
    proc = ExpressSendProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.send_message = AsyncMock(side_effect=RuntimeError("BotX 502"))

    # Also stub metrics recording to avoid ProviderError
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=error_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.core.di.providers.cache.get_record_express_message_sent_provider",
        side_effect=ImportError("metrics unavailable"),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert captured.get("express_sync_id_error") == "BotX 502"


@pytest.mark.asyncio
async def test_process_success_records_metrics_ok() -> None:
    """При успешной отправке — record_express_message_sent(status='ok')."""
    proc = ExpressSendProcessor(body="text")
    ex, _captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient(sync_id="sync-1")
    metrics_calls: list[tuple[str, str]] = []

    def _record_metrics(bot: str, status: str) -> None:
        metrics_calls.append((bot, status))

    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.core.di.providers.cache.get_record_express_message_sent_provider",
        return_value=_record_metrics,
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert metrics_calls == [("main_bot", "ok")]


@pytest.mark.asyncio
async def test_process_failure_records_metrics_error() -> None:
    """При ошибке отправки — record_express_message_sent(status='error')."""
    proc = ExpressSendProcessor(body="text")
    ex, _captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.send_message = AsyncMock(side_effect=RuntimeError("failure"))

    metrics_calls: list[tuple[str, str]] = []

    def _record_metrics(bot: str, status: str) -> None:
        metrics_calls.append((bot, status))

    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=error_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.core.di.providers.cache.get_record_express_message_sent_provider",
        return_value=_record_metrics,
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        await proc.process(ex, _ctx())

    assert metrics_calls == [("main_bot", "error")]


@pytest.mark.asyncio
async def test_process_metrics_provider_missing_does_not_break() -> None:
    """Если get_record_express_message_sent_provider raises — логируется, не падает."""
    proc = ExpressSendProcessor(body="text")
    ex, captured = _make_exchange(properties={"group_chat_id": "chat-1"})

    fake_client = _FakeClient(sync_id="sync-1")
    with patch(
        "src.backend.dsl.engine.processors.express.send.get_express_client",
        return_value=fake_client,
    ), patch(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        return_value=MagicMock(
            BotxButton=_FakeBotxButton, BotxMessage=_FakeBotxMessage
        ),
    ), patch(
        "src.backend.core.di.providers.cache.get_record_express_message_sent_provider",
        side_effect=ImportError("metrics unavailable"),
    ), patch(
        "src.backend.dsl.engine.processors.express.send.resolve_value",
        lambda exch, expr: "chat-1",
    ):
        # Should NOT raise — metrics fail is debugged internally
        await proc.process(ex, _ctx())

    assert captured["express_sync_id"] == "sync-1"


# ─────────── to_spec ───────────


def test_to_spec_minimal() -> None:
    proc = ExpressSendProcessor(body="hello")
    spec = proc.to_spec()
    assert spec == {
        "express_send": {
            "bot": "main_bot",
            "chat_id_from": "body.group_chat_id",
            "status": "ok",
            "silent_response": False,
            "sync": False,
            "result_property": "express_sync_id",
            "body": "hello",
        }
    }


def test_to_spec_with_bubble_keyboard_body_from() -> None:
    proc = ExpressSendProcessor(
        body_from="properties.text",
        bubble=[[{"command": "b1", "label": "B1"}]],
        keyboard=[[{"command": "k1", "label": "K1"}]],
        sync=True,
        silent_response=True,
    )
    spec = proc.to_spec()
    assert spec["express_send"]["body_from"] == "properties.text"
    assert spec["express_send"]["bubble"] == [[{"command": "b1", "label": "B1"}]]
    assert spec["express_send"]["keyboard"] == [[{"command": "k1", "label": "K1"}]]
    assert spec["express_send"]["sync"] is True
    assert spec["express_send"]["silent_response"] is True
    assert "body" not in spec["express_send"]


def test_to_spec_empty_bubble_keyboard_excluded() -> None:
    """bubble=[] / keyboard=[] (default empty) — НЕ попадают в spec."""
    proc = ExpressSendProcessor(body="x")
    spec = proc.to_spec()
    assert "bubble" not in spec["express_send"]
    assert "keyboard" not in spec["express_send"]
