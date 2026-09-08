"""Tests for src.backend.dsl.engine.processors.telegram.mention.

T3 coverage sprint cycle 14: TelegramMentionProcessor (inline mention fragment).
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.telegram.mention import TelegramMentionProcessor


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


class _FakeTelegramMention:
    """Match TelegramMention contract."""

    def __init__(self, *, user_id: int, display_name: str, parse_mode: str) -> None:
        self.user_id = user_id
        self.display_name = display_name
        self.parse_mode = parse_mode

    def to_inline(self) -> str:
        if self.parse_mode == "HTML":
            return f'<a href="tg://user?id={self.user_id}">{self.display_name}</a>'
        if self.parse_mode == "MarkdownV2":
            return f"[{self.display_name}](tg://user?id={self.user_id})"
        return f"{self.display_name}"


# ─────────── __init__ ───────────


def test_init_requires_user_id_from() -> None:
    """user_id_from — обязательный positional."""
    # Note: user_id_from имеет no default — TypeError если не передан
    with pytest.raises(TypeError):
        TelegramMentionProcessor()  # type: ignore[call-arg]


def test_init_defaults() -> None:
    proc = TelegramMentionProcessor(user_id_from="body.user_id")
    assert proc._user_id_from == "body.user_id"
    assert proc._display_name_from is None
    assert proc._parse_mode == "MarkdownV2"
    assert proc._property_name == "telegram_mention"
    assert proc._append is False


def test_init_invalid_parse_mode_raises() -> None:
    with pytest.raises(ValueError, match="parse_mode.*не поддерживается"):
        TelegramMentionProcessor(user_id_from="body.id", parse_mode="Plain")


def test_init_custom_parse_mode() -> None:
    proc = TelegramMentionProcessor(user_id_from="body.id", parse_mode="HTML")
    assert proc._parse_mode == "HTML"


def test_init_append_true() -> None:
    proc = TelegramMentionProcessor(user_id_from="body.id", append=True)
    assert proc._append is True


# ─────────── to_spec ───────────


def test_to_spec_minimal() -> None:
    proc = TelegramMentionProcessor(user_id_from="body.user_id")
    spec = proc.to_spec()
    assert spec == {
        "telegram_mention": {
            "user_id_from": "body.user_id",
            "parse_mode": "MarkdownV2",
            "property_name": "telegram_mention",
            "append": False,
        }
    }


def test_to_spec_with_display_name_from() -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id", display_name_from="body.name"
    )
    spec = proc.to_spec()
    assert spec["telegram_mention"]["display_name_from"] == "body.name"


# ─────────── process() ───────────


@pytest.fixture(autouse=True)
def _patch_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    """Auto-use: every test patches TelegramMention via DI provider."""
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_telegram_bot_provider",
        MagicMock(return_value=MagicMock(TelegramMention=_FakeTelegramMention)),
    )


@pytest.mark.asyncio
async def test_process_writes_inline_fragment(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id", parse_mode="MarkdownV2"
    )
    ex, captured = _make_exchange(properties={"user_id": 12345})

    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
            lambda exch, expr: 12345,
        )
        await proc.process(ex, _ctx())

    assert "[user_12345](tg://user?id=12345)" == captured["telegram_mention"]


@pytest.mark.asyncio
async def test_process_skips_when_user_id_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(user_id_from="body.user_id")
    ex, captured = _make_exchange()

    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
        MagicMock(return_value=None),
    )
        await proc.process(ex, _ctx())

    assert "telegram_mention" not in captured


@pytest.mark.asyncio
async def test_process_skips_when_user_id_not_int(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если user_id не парсится в int → skip."""
    proc = TelegramMentionProcessor(user_id_from="body.user_id")
    ex, captured = _make_exchange()

    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
        MagicMock(return_value="not-a-number"),
    )
        await proc.process(ex, _ctx())

    assert "telegram_mention" not in captured


@pytest.mark.asyncio
async def test_process_uses_display_name_from(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id",
        display_name_from="body.name",
        parse_mode="MarkdownV2",
    )
    ex, captured = _make_exchange(properties={"user_id": 42, "name": "Alice"})

    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
            lambda exch, expr: {"body.user_id": 42, "body.name": "Alice"}.get(expr),
        )
        await proc.process(ex, _ctx())

    assert captured["telegram_mention"] == "[Alice](tg://user?id=42)"


@pytest.mark.asyncio
async def test_process_display_name_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если display_name_from пуст → 'user_<id>'."""
    proc = TelegramMentionProcessor(user_id_from="body.user_id")
    ex, captured = _make_exchange(properties={"user_id": 999})

    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
        MagicMock(return_value=999),
    )
        await proc.process(ex, _ctx())

    assert captured["telegram_mention"] == "[user_999](tg://user?id=999)"


@pytest.mark.asyncio
async def test_process_html_format(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id",
        display_name_from="body.name",
        parse_mode="HTML",
    )
    ex, captured = _make_exchange(properties={"user_id": 7, "name": "Bob"})

    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
            lambda exch, expr: {"body.user_id": 7, "body.name": "Bob"}.get(expr),
        )
        await proc.process(ex, _ctx())

    assert (
        captured["telegram_mention"]
        == '<a href="tg://user?id=7">Bob</a>'
    )


@pytest.mark.asyncio
async def test_process_append_concatenates(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id",
        display_name_from="body.name",
        append=True,
    )
    existing_mention = "[First](tg://user?id=1)"
    ex, captured = _make_exchange(
        properties={"user_id": 2, "name": "Second", "telegram_mention": existing_mention}
    )

    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
            lambda exch, expr: {"body.user_id": 2, "body.name": "Second"}.get(expr),
        )
        await proc.process(ex, _ctx())

    assert (
        captured["telegram_mention"]
        == f"{existing_mention} [Second](tg://user?id=2)"
    )


@pytest.mark.asyncio
async def test_process_overwrite_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """append=False (default) → перезаписывает property."""
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id",
        display_name_from="body.name",
    )
    ex, captured = _make_exchange(
        properties={"user_id": 1, "name": "Alice", "telegram_mention": "[OLD]"}
    )

    with monkeypatch.context() as m:
        m.setattr(
            "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
            lambda exch, expr: {"body.user_id": 1, "body.name": "Alice"}.get(expr),
        )
        await proc.process(ex, _ctx())

    assert captured["telegram_mention"] == "[Alice](tg://user?id=1)"


@pytest.mark.asyncio
async def test_process_custom_property_name(monkeypatch: pytest.MonkeyPatch) -> None:
    proc = TelegramMentionProcessor(
        user_id_from="body.user_id",
        property_name="custom_mention_field",
    )
    ex, captured = _make_exchange(properties={"user_id": 11})

    with monkeypatch.context() as m:
        m.setattr(
        "src.backend.dsl.engine.processors.telegram.mention.resolve_value",
        MagicMock(return_value=11),
    )
        await proc.process(ex, _ctx())

    assert "custom_mention_field" in captured
    assert "[user_11](tg://user?id=11)" == captured["custom_mention_field"]
