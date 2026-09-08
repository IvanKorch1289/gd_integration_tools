"""Tests for src.backend.dsl.engine.processors.telegram.status.

T3 coverage sprint cycle 9: TelegramStatusProcessor (health-check через getMe).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.status import TelegramStatusProcessor


def _make_exchange() -> tuple[Exchange, dict]:
    captured: dict = {}
    ex = MagicMock(spec=Exchange)
    ex.properties = {}

    def _set_property(key: str, value: object) -> None:
        captured[key] = value

    ex.set_property = _set_property  # type: ignore[attr-defined]
    return ex, captured


def _ctx() -> ExecutionContext:
    return MagicMock(spec=ExecutionContext)


class _FakeClient:
    """Async context manager + get_me stub."""

    def __init__(self, profile: dict | Exception | None = None) -> None:
        self.profile = profile
        self.get_me_calls: int = 0

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get_me(self) -> dict:
        self.get_me_calls += 1
        if isinstance(self.profile, Exception):
            raise self.profile
        if self.profile is None:
            return {}
        return self.profile


def test_init_defaults() -> None:
    proc = TelegramStatusProcessor()
    assert proc._bot == "main_bot"
    assert proc._result_property == "telegram_bot_profile"


def test_init_custom_bot_and_property() -> None:
    proc = TelegramStatusProcessor(bot="custom_bot", result_property="custom_profile")
    assert proc._bot == "custom_bot"
    assert proc._result_property == "custom_profile"


def test_to_spec_minimal() -> None:
    proc = TelegramStatusProcessor()
    spec = proc.to_spec()
    assert spec == {
        "telegram_status": {
            "bot": "main_bot",
            "result_property": "telegram_bot_profile",
        }
    }


def test_to_spec_custom_values() -> None:
    proc = TelegramStatusProcessor(bot="bot-1", result_property="my_profile")
    spec = proc.to_spec()
    assert spec == {
        "telegram_status": {"bot": "bot-1", "result_property": "my_profile"}
    }


@pytest.mark.asyncio
async def test_process_gets_profile_and_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramStatusProcessor()
    ex, captured = _make_exchange()

    profile = {
        "id": 12345,
        "is_bot": True,
        "first_name": "TestBot",
        "username": "test_bot",
    }
    client = _FakeClient(profile=profile)

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        lambda bot_name: client,
    )

    await proc.process(ex, _ctx())

    assert client.get_me_calls == 1
    assert captured["telegram_bot_profile"] == profile


@pytest.mark.asyncio
async def test_process_skips_when_client_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_telegram_client returns None → graceful no-op."""
    proc = TelegramStatusProcessor()
    ex, captured = _make_exchange()

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        lambda bot_name: None,
    )

    await proc.process(ex, _ctx())

    assert "telegram_bot_profile" not in captured


@pytest.mark.asyncio
async def test_process_exception_records_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_me raises → records ``{result_property}_error``."""
    proc = TelegramStatusProcessor()
    ex, captured = _make_exchange()

    client = _FakeClient(profile=RuntimeError("Telegram API 401"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        lambda bot_name: client,
    )

    await proc.process(ex, _ctx())

    assert captured.get("telegram_bot_profile_error") == "Telegram API 401"


@pytest.mark.asyncio
async def test_process_custom_result_property(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramStatusProcessor(result_property="custom_profile")
    ex, captured = _make_exchange()

    profile = {"id": 99}
    client = _FakeClient(profile=profile)

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        lambda bot_name: client,
    )

    await proc.process(ex, _ctx())

    assert captured.get("custom_profile") == profile


@pytest.mark.asyncio
async def test_process_custom_exception_property(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramStatusProcessor(result_property="custom_profile")
    ex, captured = _make_exchange()

    client = _FakeClient(profile=ValueError("bad request"))

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        lambda bot_name: client,
    )

    await proc.process(ex, _ctx())

    assert captured.get("custom_profile_error") == "bad request"


@pytest.mark.asyncio
async def test_process_passes_bot_name(monkeypatch: pytest.MonkeyPatch) -> None:
    """get_telegram_client called with correct bot name."""
    proc = TelegramStatusProcessor(bot="specific_bot")
    ex, _captured = _make_exchange()

    captured_calls: list[str] = []

    def _factory(bot_name: str) -> _FakeClient:
        captured_calls.append(bot_name)
        return _FakeClient(profile={"id": 1})

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.telegram.status.get_telegram_client",
        _factory,
    )

    await proc.process(ex, _ctx())

    # Single call from process() with the right bot_name
    assert captured_calls == ["specific_bot"]
