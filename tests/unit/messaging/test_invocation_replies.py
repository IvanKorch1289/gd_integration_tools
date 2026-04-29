"""Unit-тесты для :class:`InvocationReplyChannel` backends (W22.3)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.core.interfaces.invocation_reply import ReplyChannelKind
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationResponse,
    InvocationStatus,
)
from src.infrastructure.messaging.invocation_replies import (
    MemoryReplyChannel,
    ReplyChannelRegistry,
    WsReplyChannel,
)


def _response(invocation_id: str = "i-1", result: Any = None) -> InvocationResponse:
    return InvocationResponse(
        invocation_id=invocation_id,
        status=InvocationStatus.OK,
        result=result,
        mode=InvocationMode.ASYNC_API,
    )


class TestMemoryReplyChannel:
    """In-memory polling backend."""

    async def test_kind_is_api(self) -> None:
        channel = MemoryReplyChannel()
        assert channel.kind is ReplyChannelKind.API

    async def test_send_then_fetch_returns_response(self) -> None:
        channel = MemoryReplyChannel()
        response = _response("i-42", result={"ok": True})

        await channel.send(response)
        fetched = await channel.fetch("i-42")

        assert fetched is response

    async def test_fetch_unknown_returns_none(self) -> None:
        channel = MemoryReplyChannel()
        assert await channel.fetch("missing") is None

    async def test_send_overwrites_previous(self) -> None:
        channel = MemoryReplyChannel()
        await channel.send(_response("i-1", result="v1"))
        await channel.send(_response("i-1", result="v2"))

        fetched = await channel.fetch("i-1")
        assert fetched is not None
        assert fetched.result == "v2"

    async def test_max_entries_evicts_oldest(self) -> None:
        channel = MemoryReplyChannel(max_entries=3)
        for idx in range(5):
            await channel.send(_response(f"i-{idx}"))

        # Самые старые (i-0, i-1) вытеснены, остались последние 3.
        assert await channel.fetch("i-0") is None
        assert await channel.fetch("i-1") is None
        for idx in range(2, 5):
            assert await channel.fetch(f"i-{idx}") is not None

    async def test_ttl_expiry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """По истечении TTL fetch возвращает None и удаляет запись."""
        from src.infrastructure.messaging.invocation_replies import memory as mem_mod

        time_ref = [1000.0]

        def fake_monotonic() -> float:
            return time_ref[0]

        monkeypatch.setattr(mem_mod, "monotonic", fake_monotonic)

        channel = MemoryReplyChannel(ttl_seconds=10)
        await channel.send(_response("i-ttl"))
        assert await channel.fetch("i-ttl") is not None

        time_ref[0] = 1100.0
        assert await channel.fetch("i-ttl") is None


class _StubWs:
    """Минимальная mock-реализация WsConnection."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


class TestWsReplyChannel:
    """WebSocket push-канал."""

    async def test_kind_is_ws(self) -> None:
        channel = WsReplyChannel()
        assert channel.kind is ReplyChannelKind.WS

    async def test_send_pushes_to_registered_connection(self) -> None:
        channel = WsReplyChannel()
        ws = _StubWs()
        await channel.register("i-7", ws)

        await channel.send(_response("i-7", result={"v": 1}))

        assert len(ws.sent) == 1
        assert ws.sent[0]["invocation_id"] == "i-7"
        assert ws.sent[0]["status"] == "ok"
        assert ws.sent[0]["result"] == {"v": 1}

    async def test_send_without_connection_is_noop(self) -> None:
        channel = WsReplyChannel()
        # Не должно бросать исключений.
        await channel.send(_response("i-no-conn"))

    async def test_unregister_removes_connection(self) -> None:
        channel = WsReplyChannel()
        ws = _StubWs()
        await channel.register("i-1", ws)
        await channel.unregister("i-1")

        await channel.send(_response("i-1"))
        assert ws.sent == []

    async def test_send_swallows_ws_errors(self) -> None:
        channel = WsReplyChannel()
        ws = AsyncMock()
        ws.send_json.side_effect = RuntimeError("connection broken")
        await channel.register("i-err", ws)

        await channel.send(_response("i-err"))

    async def test_fetch_always_returns_none(self) -> None:
        channel = WsReplyChannel()
        ws = _StubWs()
        await channel.register("i-1", ws)
        await channel.send(_response("i-1"))

        assert await channel.fetch("i-1") is None


class TestReplyChannelRegistry:
    """Registry с регистрацией по kind."""

    def test_register_and_get_by_enum(self) -> None:
        registry = ReplyChannelRegistry()
        memory = MemoryReplyChannel()
        registry.register(memory)
        assert registry.get(ReplyChannelKind.API) is memory

    def test_register_and_get_by_string(self) -> None:
        registry = ReplyChannelRegistry()
        memory = MemoryReplyChannel()
        registry.register(memory)
        assert registry.get("api") is memory

    def test_get_invalid_kind_returns_none(self) -> None:
        registry = ReplyChannelRegistry()
        assert registry.get("not-a-kind") is None

    def test_register_overrides_existing(self) -> None:
        registry = ReplyChannelRegistry()
        first = MemoryReplyChannel()
        second = MemoryReplyChannel()
        registry.register(first)
        registry.register(second)
        assert registry.get(ReplyChannelKind.API) is second

    def test_kinds_lists_all_registered(self) -> None:
        registry = ReplyChannelRegistry()
        registry.register(MemoryReplyChannel())
        registry.register(WsReplyChannel())
        assert set(registry.kinds()) == {ReplyChannelKind.API, ReplyChannelKind.WS}
