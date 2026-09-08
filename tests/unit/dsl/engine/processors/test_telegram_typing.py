"""Tests for src.backend.dsl.engine.processors.telegram.typing.

T3 coverage sprint cycle 12: TelegramTypingProcessor (chat-action: typing).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.typing import TelegramTypingProcessor


def _make_exchange(properties: dict | None = None) -> tuple[Exchange, dict]:
    captured: dict = {}
    ex = MagicMock(spec=Exchange)
    ex.properties = properties or {}

    def _set_property(key: str, value: object) -> None:
        captured[key] = value

    ex.set_property = _set_property  # type: ignore[attr-defined]
    return ex, captured


def _ctx() -> ExecutionContext:
    return MagicMock(spec=ExecutionContext)


# ─────────── __init__ ───────────


def test_init_defaults() -> None:
    proc = TelegramTypingProcessor()
    assert proc._bot == "main_bot"
    assert proc._chat_id_from == "body.chat_id"
    assert proc._action == "typing"


def test_init_custom_action() -> None:
    proc = TelegramTypingProcessor(action="upload_photo")
    assert proc._action == "upload_photo"


def test_init_invalid_action_raises() -> None:
    with pytest.raises(ValueError, match="неверный action"):
        TelegramTypingProcessor(action="invalid_action")


# ─────────── to_spec ───────────


def test_to_spec_minimal() -> None:
    proc = TelegramTypingProcessor()
    spec = proc.to_spec()
    assert spec == {
        "telegram_typing": {
            "bot": "main_bot",
            "chat_id_from": "body.chat_id",
            "action": "typing",
        }
    }


def test_to_spec_custom_action() -> None:
    proc = TelegramTypingProcessor(action="upload_photo", bot="custom_bot")
    spec = proc.to_spec()
    assert spec == {
        "telegram_typing": {
            "bot": "custom_bot",
            "chat_id_from": "body.chat_id",
            "action": "upload_photo",
        }
    }


# ─────────── process() ───────────


class _FakeClient:
    def __init__(self) -> None:
        self.send_calls: list[tuple[str, str]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def send_chat_action(self, chat_id: str, action: str) -> None:
        self.send_calls.append((chat_id, action))


@pytest.mark.asyncio
async def test_process_sends_chat_action(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramTypingProcessor()
    ex, _captured = _make_exchange(properties={"chat_id": "123"})

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: "123",
    ):
        await proc.process(ex, _ctx())

    assert len(fake_client.send_calls) == 1
    chat_id_arg, action_arg = fake_client.send_calls[0]
    assert chat_id_arg == "123"
    assert action_arg == "typing"


@pytest.mark.asyncio
async def test_process_skips_when_chat_id_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramTypingProcessor()
    ex, captured = _make_exchange()

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        return_value=None,
    ):
        await proc.process(ex, _ctx())

    assert fake_client.send_calls == []
    assert "set_property" not in str(captured)  # no side effects


@pytest.mark.asyncio
async def test_process_client_none_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramTypingProcessor()
    ex, captured = _make_exchange(properties={"chat_id": "123"})

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        MagicMock(return_value=None),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: "123",
    ):
        await proc.process(ex, _ctx())

    # No send_chat_action called, no error recorded
    assert "set_property" not in str(captured)


@pytest.mark.asyncio
async def test_process_exception_silently_logged(monkeypatch: pytest.MonkeyPatch) -> None:
    """Exception in send_chat_action is logged but does NOT raise (no fail property)."""
    proc = TelegramTypingProcessor()
    ex, captured = _make_exchange(properties={"chat_id": "123"})

    error_client = MagicMock()
    error_client.__aenter__ = AsyncMock(return_value=error_client)
    error_client.__aexit__ = AsyncMock(return_value=None)
    error_client.send_chat_action = AsyncMock(side_effect=RuntimeError("Bot API 429"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        MagicMock(return_value=error_client),
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: "123",
    ):
        # Should NOT raise
        await proc.process(ex, _ctx())

    # No error property recorded (best-effort action — silently logged)
    assert "set_property" not in str(captured)


@pytest.mark.asyncio
async def test_process_chat_id_coerced_to_str(monkeypatch: pytest.MonkeyPatch) -> None:
    """chat_id всегда приводится к str перед отправке в client."""
    proc = TelegramTypingProcessor()
    ex, _captured = _make_exchange()

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: 99999,
    ):
        await proc.process(ex, _ctx())

    chat_id_arg = fake_client.send_calls[0][0]
    assert chat_id_arg == "99999"
    assert isinstance(chat_id_arg, str)


@pytest.mark.asyncio
async def test_process_passes_correct_bot_name(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramTypingProcessor(bot="specific_bot")
    ex, _captured = _make_exchange(properties={"chat_id": "123"})

    captured_calls: list[str] = []

    def _factory(bot_name: str) -> _FakeClient:
        captured_calls.append(bot_name)
        return _FakeClient()

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        _factory,
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: "123",
    ):
        await proc.process(ex, _ctx())

    assert captured_calls == ["specific_bot"]


@pytest.mark.asyncio
async def test_process_passes_correct_action(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramTypingProcessor(action="upload_photo")
    ex, _captured = _make_exchange(properties={"chat_id": "123"})

    fake_client = _FakeClient()
    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.typing.get_telegram_client",
        lambda bot_name: fake_client,
    )
    with patch(
        "src.backend.dsl.engine.processors.telegram.typing.resolve_value",
        lambda exch, expr: "123",
    ):
        await proc.process(ex, _ctx())

    assert fake_client.send_calls[0][1] == "upload_photo"
