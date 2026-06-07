"""Advanced unit tests for RequestReplyMixin, RequestReplyBackend, InMemoryTransport."""

from __future__ import annotations

import asyncio
import pytest

from src.backend.dsl.builders.request_reply_mixin import (
    DEFAULT_TIMEOUT_S,
    REPLY_CHANNEL_PREFIX,
    InMemoryTransport,
    RequestReplyBackend,
    RequestReplyMixin,
    RequestReplyTimeoutError,
)


# ============================================================================
# InMemoryTransport
# ============================================================================


@pytest.mark.asyncio
async def test_inmemory_transport_publish_subscribe_round_trip() -> None:
    transport = InMemoryTransport()
    received: list[dict] = []

    async def handler(envelope: dict) -> None:
        received.append(envelope)

    await transport.subscribe("ch1", handler)
    await transport.publish("ch1", {"msg": "hello"})

    assert len(received) == 1
    assert received[0] == {"msg": "hello"}
    assert transport.log == [("subscribe", "ch1"), ("publish", "ch1")]


@pytest.mark.asyncio
async def test_inmemory_transport_multiple_subscribers_get_copy() -> None:
    transport = InMemoryTransport()
    received_a: list[dict] = []
    received_b: list[dict] = []

    async def handler_a(envelope: dict) -> None:
        received_a.append(envelope)

    async def handler_b(envelope: dict) -> None:
        received_b.append(envelope)

    await transport.subscribe("ch1", handler_a)
    await transport.subscribe("ch1", handler_b)
    await transport.publish("ch1", {"msg": "hi"})

    assert len(received_a) == 1
    assert len(received_b) == 1
    assert received_a[0] == received_b[0]
    assert transport.log.count(("publish", "ch1")) == 1
    assert transport.log.count(("subscribe", "ch1")) == 2


@pytest.mark.asyncio
async def test_inmemory_transport_no_subscriber_does_not_raise() -> None:
    transport = InMemoryTransport()
    await transport.publish("void", {"msg": "orphan"})
    assert transport.log == [("publish", "void")]


# ============================================================================
# RequestReplyBackend
# ============================================================================


@pytest.mark.asyncio
async def test_backend_request_reply_round_trip() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    async def replier() -> None:
        # simulate remote replier: read from transport subscriber
        # but we don't have direct access; instead, just call backend.reply
        # after a tiny delay to let request subscribe first.
        await asyncio.sleep(0.01)
        await backend.reply("cid-123", {"result": "ok"})

    asyncio.create_task(replier())
    result = await backend.request(
        "endpoint", {"action": "test"}, correlation_id="cid-123"
    )

    assert result == {"result": "ok"}
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_request_timeout() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    with pytest.raises(RequestReplyTimeoutError) as exc_info:
        await backend.request("endpoint", {"action": "test"}, timeout=0.05)

    assert "timeout after 0.05s" in str(exc_info.value)
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_wait_for_reply_timeout() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    with pytest.raises(RequestReplyTimeoutError) as exc_info:
        await backend.wait_for_reply("cid-wait", timeout=0.05)

    assert "wait_for_reply timeout after 0.05s" in str(exc_info.value)
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_duplicate_correlation_id_request() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    # Block first request so cid stays pending
    task = asyncio.create_task(
        backend.request("endpoint", {"a": 1}, correlation_id="dup", timeout=10.0)
    )
    await asyncio.sleep(0)  # let request acquire lock and register pending

    with pytest.raises(ValueError, match="duplicate correlation_id: 'dup'"):
        await backend.request("endpoint", {"a": 2}, correlation_id="dup")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_backend_wait_for_reply_duplicate_cid() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    task = asyncio.create_task(backend.wait_for_reply("dup-wait", timeout=10.0))
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="correlation_id 'dup-wait' already pending"):
        await backend.wait_for_reply("dup-wait")

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_backend_reply_without_pending_future_does_not_raise() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    # Publishing a reply when nobody waits should be harmless
    await backend.reply("orphan-cid", {"result": "none"})
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_on_reply_missing_cid() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    # _on_reply with no correlation_id should return early
    await backend._on_reply({"payload": "no-cid"})
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_wait_for_reply_success() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    async def replier() -> None:
        await asyncio.sleep(0.01)
        await backend.reply("wait-cid", "pong")

    asyncio.create_task(replier())
    result = await backend.wait_for_reply("wait-cid", timeout=DEFAULT_TIMEOUT_S)
    assert result == "pong"
    assert backend.pending_count == 0


@pytest.mark.asyncio
async def test_backend_request_auto_generates_cid() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    captured: list[dict] = []

    async def capture_handler(envelope: dict) -> None:
        captured.append(envelope)

    await transport.subscribe("endpoint", capture_handler)

    async def replier() -> None:
        await asyncio.sleep(0.01)
        assert len(captured) == 1
        cid = captured[0]["correlation_id"]
        await backend.reply(cid, "auto-ok")

    asyncio.create_task(replier())
    result = await backend.request("endpoint", {"a": 1})
    assert result == "auto-ok"


@pytest.mark.asyncio
async def test_backend_ensure_subscribed_idempotent() -> None:
    transport = InMemoryTransport()
    backend = RequestReplyBackend(transport)

    ch = backend.reply_channel("cid-x")
    await backend._ensure_subscribed(ch)
    await backend._ensure_subscribed(ch)

    # Only one subscribe call should be logged
    assert transport.log.count(("subscribe", ch)) == 1


# ============================================================================
# RequestReplyMixin
# ============================================================================


class Dummy(RequestReplyMixin):
    """Minimal concrete class for mixin tests."""

    __slots__ = ("_rr_backend", "_rr_transport")


@pytest.mark.asyncio
async def test_mixin_attach_transport_returns_self() -> None:
    dummy = Dummy()
    transport = InMemoryTransport()
    assert dummy.attach_transport(transport) is dummy


@pytest.mark.asyncio
async def test_mixin_request_reply_round_trip() -> None:
    dummy = Dummy()
    backend = dummy._request_reply_backend()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        await backend.reply("mix-cid", "hello-mixin")

    asyncio.create_task(replier())
    result = await dummy.request("ep", payload={"x": 1}, correlation_id="mix-cid")
    assert result == "hello-mixin"


@pytest.mark.asyncio
async def test_mixin_reply_and_wait_for_reply() -> None:
    dummy = Dummy()

    async def replier() -> None:
        await asyncio.sleep(0.01)
        await dummy.reply("wait-mix", "delayed")

    asyncio.create_task(replier())
    result = await dummy.wait_for_reply("wait-mix", timeout=1.0)
    assert result == "delayed"


@pytest.mark.asyncio
async def test_mixin_attach_transport_changes_backend() -> None:
    dummy = Dummy()
    old_backend = dummy._request_reply_backend()

    new_transport = InMemoryTransport()
    dummy.attach_transport(new_transport)

    new_backend = dummy._request_reply_backend()
    assert new_backend is not old_backend
    assert new_backend.transport is new_transport


@pytest.mark.asyncio
async def test_mixin_request_timeout() -> None:
    dummy = Dummy()
    with pytest.raises(RequestReplyTimeoutError):
        await dummy.request("ep", payload={"x": 1}, timeout=0.05)


@pytest.mark.asyncio
async def test_mixin_wait_for_reply_timeout() -> None:
    dummy = Dummy()
    with pytest.raises(RequestReplyTimeoutError):
        await dummy.wait_for_reply("missing", timeout=0.05)
