"""Tests for src.backend.dsl.engine.processors.express.mention.

T3 coverage sprint cycle 4: тесты для ``ExpressMentionProcessor.__init__``
(validation) и ``process`` (mention creation per type).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.express.mention import ExpressMentionProcessor


def _make_exchange(properties: dict | None = None) -> Exchange:
    """Exchange stub with properties dict + set_property hook."""
    ex = MagicMock(spec=Exchange)
    ex.properties = properties or {}
    captured: dict = {}

    def _set_property(key: str, value: object) -> None:
        captured[key] = value

    ex.set_property = _set_property  # type: ignore[attr-defined]
    ex._captured = captured  # test inspection hook
    return ex


def _ctx() -> ExecutionContext:
    return MagicMock(spec=ExecutionContext)


# ─────────── __init__ validation ───────────


def test_init_valid_types() -> None:
    """Valid mention types accepted without error (target_from required for non-all)."""
    # 'all' doesn't require target_from
    proc = ExpressMentionProcessor(mention_type="all")
    assert proc._mention_type == "all"
    # Non-all types require target_from (covered in dedicated tests)
    for mention_type in ["user", "chat", "channel", "contact"]:
        proc = ExpressMentionProcessor(mention_type=mention_type, target_from="body.id")
        assert proc._mention_type == mention_type


def test_init_invalid_type_raises() -> None:
    """Invalid mention_type raises ValueError."""
    with pytest.raises(ValueError, match="неверный mention_type"):
        ExpressMentionProcessor(mention_type="invalid")


def test_init_user_requires_target_from() -> None:
    """mention_type=user без target_from raises ValueError."""
    with pytest.raises(ValueError, match="target_from обязателен"):
        ExpressMentionProcessor(mention_type="user", target_from=None)


def test_init_chat_requires_target_from() -> None:
    with pytest.raises(ValueError, match="target_from обязателен"):
        ExpressMentionProcessor(mention_type="chat", target_from=None)


def test_init_all_does_not_require_target_from() -> None:
    """mention_type=all допустим без target_from."""
    proc = ExpressMentionProcessor(mention_type="all")
    assert proc._mention_type == "all"


def test_init_default_property_name() -> None:
    proc = ExpressMentionProcessor(mention_type="all")
    assert proc._property_name == "express_mentions"


def test_init_custom_property_name() -> None:
    proc = ExpressMentionProcessor(
        mention_type="all", property_name="custom_mentions"
    )
    assert proc._property_name == "custom_mentions"


# ─────────── process() ───────────


def _patch_express_bot_module(monkeypatch, mentions: dict[str, type]) -> None:
    """Inject a fake express_bot module with BotxMention class."""
    fake_module = MagicMock()
    fake_module.BotxMention = mentions["BotxMention"]
    monkeypatch.setattr(
        "src.backend.core.di.providers.cache.get_express_bot_module_provider",
        lambda: fake_module,
    )


class _FakeBotxMention:
    """Minimal fake matching BotxMention's __init__ contract."""

    def __init__(
        self,
        mention_type: str,
        mention_id: str,
        user_huid: str | None = None,
        name: str | None = None,
        group_chat_id: str | None = None,
    ) -> None:
        self.mention_type = mention_type
        self.mention_id = mention_id
        self.user_huid = user_huid
        self.name = name
        self.group_chat_id = group_chat_id


@pytest.mark.asyncio
async def test_process_user_type_creates_mention(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange(properties={"user_huid": "user-123"})
    proc = ExpressMentionProcessor(
        mention_type="user",
        target_from="body.user_huid",
        mention_id="mention-abc",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "user-123" if expr == "body.user_huid" else None,
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert len(captured) == 1
    assert captured[0].mention_type == "user"
    assert captured[0].user_huid == "user-123"
    assert captured[0].mention_id == "mention-abc"


@pytest.mark.asyncio
async def test_process_chat_type_sets_group_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="chat",
        target_from="body.chat_id",
        mention_id="m-chat",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "chat-uuid" if expr == "body.chat_id" else None,
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert captured[0].mention_type == "chat"
    assert captured[0].group_chat_id == "chat-uuid"
    assert captured[0].user_huid is None


@pytest.mark.asyncio
async def test_process_channel_type_sets_group_chat_id(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="channel",
        target_from="body.channel_id",
        mention_id="m-ch",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "ch-uuid" if expr == "body.channel_id" else None,
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert captured[0].mention_type == "channel"
    assert captured[0].group_chat_id == "ch-uuid"


@pytest.mark.asyncio
async def test_process_contact_type_uses_user_huid(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="contact",
        target_from="body.contact_id",
        mention_id="m-ct",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "ct-uuid" if expr == "body.contact_id" else None,
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert captured[0].mention_type == "contact"
    assert captured[0].user_huid == "ct-uuid"


@pytest.mark.asyncio
async def test_process_skips_when_target_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If resolve_value returns falsy for non-all type → no mention added."""
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="user",
        target_from="body.user_huid",
        mention_id="m",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: None,
    ):
        await proc.process(ex, _ctx())

    assert "express_mentions" not in ex._captured


@pytest.mark.asyncio
async def test_process_all_type_skips_target_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    """mention_type=all doesn't need target — generates mention без target check."""
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="all", mention_id="m-all"
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value"
    ) as mock_resolve:
        await proc.process(ex, _ctx())
        # resolve_value not called when target_from is None
        mock_resolve.assert_not_called()

    captured = ex._captured["express_mentions"]
    assert len(captured) == 1
    assert captured[0].mention_type == "all"


@pytest.mark.asyncio
async def test_process_appends_to_existing_bucket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If exchange already has list of mentions, append to it."""
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})

    existing_mention = _FakeBotxMention(
        mention_type="user", mention_id="m-old", user_huid="user-1"
    )
    ex = _make_exchange(properties={"express_mentions": [existing_mention]})
    proc = ExpressMentionProcessor(
        mention_type="user",
        target_from="body.user_huid",
        mention_id="m-new",
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "user-2",
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert len(captured) == 2
    assert captured[0].mention_id == "m-old"
    assert captured[1].mention_id == "m-new"


@pytest.mark.asyncio
async def test_process_non_list_existing_overwrites(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-list existing value is replaced (not appended) — defense against bad state."""
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange(properties={"express_mentions": "garbage-string"})
    proc = ExpressMentionProcessor(
        mention_type="all", mention_id="m"
    )

    await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    # Non-list is treated as empty — replaced by single-element list
    assert len(captured) == 1


@pytest.mark.asyncio
async def test_process_generates_uuid_when_mention_id_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """mention_id=None → uuid.uuid4().hex is generated (non-empty)."""
    _patch_express_bot_module(monkeypatch, {"BotxMention": _FakeBotxMention})
    ex = _make_exchange()
    proc = ExpressMentionProcessor(
        mention_type="user",
        target_from="body.user_huid",
        mention_id=None,
    )

    with patch(
        "src.backend.dsl.engine.processors.express.mention.resolve_value",
        lambda exch, expr: "u-1",
    ):
        await proc.process(ex, _ctx())

    captured = ex._captured["express_mentions"]
    assert captured[0].mention_id  # not empty
    assert len(captured[0].mention_id) > 0
