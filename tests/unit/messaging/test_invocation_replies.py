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


class _RecordingNotifier:
    """Минимальный mock для Email/Express notifier'ов.

    Совместим с :class:`EmailNotifier` / :class:`ExpressNotifier` Protocol —
    одинаковая kwargs-сигнатура ``send``.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def send(
        self,
        *,
        recipient: str,
        subject: str,
        body: str,
        metadata: dict[str, Any],
    ) -> None:
        self.calls.append(
            {
                "recipient": recipient,
                "subject": subject,
                "body": body,
                "metadata": metadata,
            }
        )


class TestEmailReplyChannel:
    """Push-only email канал (W22 этап B)."""

    async def test_kind_is_email(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        assert EmailReplyChannel().kind is ReplyChannelKind.EMAIL

    async def test_send_uses_metadata_email(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        notifier = _RecordingNotifier()
        channel = EmailReplyChannel(notifier=notifier)
        response = InvocationResponse(
            invocation_id="i-em",
            status=InvocationStatus.OK,
            result={"v": 42},
            mode=InvocationMode.ASYNC_API,
            metadata={"email": "user@example.com"},
        )

        await channel.send(response)

        assert len(notifier.calls) == 1
        call = notifier.calls[0]
        assert call["recipient"] == "user@example.com"
        assert "i-em" in call["subject"]
        assert "ok" in call["body"].lower()

    async def test_send_skips_without_recipient(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        notifier = _RecordingNotifier()
        channel = EmailReplyChannel(notifier=notifier)
        response = InvocationResponse(
            invocation_id="i-no-em",
            status=InvocationStatus.OK,
            mode=InvocationMode.ASYNC_API,
        )

        await channel.send(response)

        assert notifier.calls == []

    async def test_send_uses_default_recipient(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        notifier = _RecordingNotifier()
        channel = EmailReplyChannel(notifier=notifier, default_recipient="ops@x.com")
        response = InvocationResponse(
            invocation_id="i-def",
            status=InvocationStatus.OK,
            mode=InvocationMode.ASYNC_API,
        )

        await channel.send(response)

        assert notifier.calls[0]["recipient"] == "ops@x.com"

    async def test_swallows_notifier_errors(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        notifier = AsyncMock()
        notifier.send.side_effect = RuntimeError("smtp down")
        channel = EmailReplyChannel(notifier=notifier)

        # Не должно поднимать исключение.
        await channel.send(
            InvocationResponse(
                invocation_id="i-err",
                status=InvocationStatus.OK,
                mode=InvocationMode.ASYNC_API,
                metadata={"email": "x@y.z"},
            )
        )

    async def test_fetch_always_returns_none(self) -> None:
        from src.infrastructure.messaging.invocation_replies import EmailReplyChannel

        channel = EmailReplyChannel(notifier=_RecordingNotifier())
        assert await channel.fetch("i-1") is None


class TestExpressReplyChannel:
    """Push-only Express канал."""

    async def test_kind_is_express(self) -> None:
        from src.infrastructure.messaging.invocation_replies import ExpressReplyChannel

        assert ExpressReplyChannel().kind is ReplyChannelKind.EXPRESS

    async def test_send_uses_metadata_chat_id(self) -> None:
        from src.infrastructure.messaging.invocation_replies import ExpressReplyChannel

        notifier = _RecordingNotifier()
        channel = ExpressReplyChannel(notifier=notifier)
        response = InvocationResponse(
            invocation_id="i-ex",
            status=InvocationStatus.OK,
            result="hello",
            mode=InvocationMode.ASYNC_API,
            metadata={"express_chat_id": "chat-uuid-1", "bot": "ops_bot"},
        )

        await channel.send(response)

        assert len(notifier.calls) == 1
        call = notifier.calls[0]
        assert call["recipient"] == "chat-uuid-1"
        assert call["metadata"]["bot"] == "ops_bot"
        assert call["metadata"]["status"] == "ok"

    async def test_send_skips_without_chat_id(self) -> None:
        from src.infrastructure.messaging.invocation_replies import ExpressReplyChannel

        notifier = _RecordingNotifier()
        channel = ExpressReplyChannel(notifier=notifier)
        response = InvocationResponse(
            invocation_id="i-skip",
            status=InvocationStatus.OK,
            mode=InvocationMode.ASYNC_API,
        )

        await channel.send(response)

        assert notifier.calls == []

    async def test_error_status_propagates_to_metadata(self) -> None:
        from src.infrastructure.messaging.invocation_replies import ExpressReplyChannel

        notifier = _RecordingNotifier()
        channel = ExpressReplyChannel(notifier=notifier)
        response = InvocationResponse(
            invocation_id="i-fail",
            status=InvocationStatus.ERROR,
            error="bang",
            mode=InvocationMode.ASYNC_API,
            metadata={"express_chat_id": "c1"},
        )

        await channel.send(response)

        assert notifier.calls[0]["metadata"]["status"] == "error"


class TestQueueReplyChannel:
    """Push-only Redis/Rabbit/Kafka канал через произвольный publisher."""

    async def test_kind_is_queue(self) -> None:
        from src.infrastructure.messaging.invocation_replies import QueueReplyChannel

        assert QueueReplyChannel().kind is ReplyChannelKind.QUEUE

    async def test_publishes_to_metadata_topic(self) -> None:
        from src.infrastructure.messaging.invocation_replies import QueueReplyChannel

        captured: list[tuple[str, dict[str, Any]]] = []

        async def _publisher(topic: str, message: dict[str, Any]) -> None:
            captured.append((topic, message))

        channel = QueueReplyChannel(publisher=_publisher)
        response = InvocationResponse(
            invocation_id="i-q",
            status=InvocationStatus.OK,
            result={"x": 1},
            mode=InvocationMode.ASYNC_API,
            metadata={"queue_topic": "results.in"},
        )

        await channel.send(response)

        assert len(captured) == 1
        topic, message = captured[0]
        assert topic == "results.in"
        assert message["invocation_id"] == "i-q"
        assert message["status"] == "ok"
        assert message["result"] == {"x": 1}

    async def test_skip_without_topic(self) -> None:
        from src.infrastructure.messaging.invocation_replies import QueueReplyChannel

        captured: list[tuple[str, dict[str, Any]]] = []

        async def _publisher(topic: str, message: dict[str, Any]) -> None:
            captured.append((topic, message))

        channel = QueueReplyChannel(publisher=_publisher)
        response = InvocationResponse(
            invocation_id="i-no-topic",
            status=InvocationStatus.OK,
            mode=InvocationMode.ASYNC_API,
        )

        await channel.send(response)
        assert captured == []

    async def test_default_topic_used_when_metadata_missing(self) -> None:
        from src.infrastructure.messaging.invocation_replies import QueueReplyChannel

        captured: list[tuple[str, dict[str, Any]]] = []

        async def _publisher(topic: str, message: dict[str, Any]) -> None:
            captured.append((topic, message))

        channel = QueueReplyChannel(
            publisher=_publisher, default_topic="invocations.results"
        )
        response = InvocationResponse(
            invocation_id="i-d",
            status=InvocationStatus.OK,
            mode=InvocationMode.ASYNC_API,
        )

        await channel.send(response)

        assert captured[0][0] == "invocations.results"

    async def test_swallows_publisher_errors(self) -> None:
        from src.infrastructure.messaging.invocation_replies import QueueReplyChannel

        async def _broken(topic: str, message: dict[str, Any]) -> None:
            raise RuntimeError("broker down")

        channel = QueueReplyChannel(publisher=_broken)
        # Не должно поднимать исключение.
        await channel.send(
            InvocationResponse(
                invocation_id="i-err",
                status=InvocationStatus.OK,
                mode=InvocationMode.ASYNC_API,
                metadata={"queue_topic": "t1"},
            )
        )
