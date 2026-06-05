"""Unit-tests for ReplyChannelRegistry."""

from __future__ import annotations

from src.backend.core.interfaces.invocation_reply import (
    InvocationReplyChannel,
    ReplyChannelKind,
)
from src.backend.infrastructure.messaging.invocation_replies.registry import (
    ReplyChannelRegistry,
    get_reply_channel_registry,
)


class _FakeChannel(InvocationReplyChannel):
    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind("api")

    async def send(self, payload: dict, metadata: dict | None = None) -> None:
        pass


class _FakeWsChannel(InvocationReplyChannel):
    @property
    def kind(self) -> ReplyChannelKind:
        return ReplyChannelKind("ws")

    async def send(self, payload: dict, metadata: dict | None = None) -> None:
        pass


def test_register_and_get() -> None:
    registry = ReplyChannelRegistry()
    ch = _FakeChannel()
    registry.register(ch)
    assert registry.get(ReplyChannelKind.API) is ch


def test_get_by_string() -> None:
    registry = ReplyChannelRegistry()
    ch = _FakeChannel()
    registry.register(ch)
    assert registry.get("api") is ch


def test_get_invalid_string_returns_none() -> None:
    registry = ReplyChannelRegistry()
    assert registry.get("unknown") is None


def test_register_overwrites_same_kind() -> None:
    registry = ReplyChannelRegistry()
    ch1 = _FakeChannel()
    ch2 = _FakeChannel()
    registry.register(ch1)
    registry.register(ch2)
    assert registry.get(ReplyChannelKind.API) is ch2


def test_kinds() -> None:
    registry = ReplyChannelRegistry()
    registry.register(_FakeChannel())
    registry.register(_FakeWsChannel())
    assert set(registry.kinds()) == {ReplyChannelKind.API, ReplyChannelKind.WS}


def test_get_reply_channel_registry_singleton() -> None:
    reg1 = get_reply_channel_registry()
    reg2 = get_reply_channel_registry()
    assert reg1 is reg2
