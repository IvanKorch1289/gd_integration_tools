"""Unit tests для EIP reliability patterns (Sprint 56 W3).

Coverage:
* CorrelationIdentifierProcessor — 3 tests
* MessageExpirationProcessor — 3 tests
* RedeliveryPolicyProcessor — 3 tests
* ReturnAddressProcessor — 3 tests
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.eip.reliability import (
    HEADER_CORRELATION_ID,
    HEADER_REDELIVERY_COUNT,
    HEADER_RETURN_ADDRESS,
    CorrelationIdentifierProcessor,
    MessageExpirationProcessor,
    RedeliveryPolicyProcessor,
    ReturnAddressProcessor,
)


def _exchange(body: object = "", headers: dict | None = None) -> Exchange:
    msg = Message(body=body, headers=headers or {})
    return Exchange(in_message=msg)


def _ctx() -> ExecutionContext:
    return ExecutionContext()


# ── CorrelationIdentifierProcessor ──────────────────────────────────


class TestCorrelationIdentifier:
    @pytest.mark.asyncio
    async def test_generates_uuid_when_no_existing(self) -> None:
        """Нет existing header → UUID4 генерируется + meta синхронизируется."""
        op = CorrelationIdentifierProcessor()
        ex = _exchange({})
        await op.process(ex, _ctx())
        cid = ex.in_message.get_header(HEADER_CORRELATION_ID)
        assert cid is not None
        assert ex.meta.correlation_id == cid
        assert op.stats()["generated"] == 1

    @pytest.mark.asyncio
    async def test_preserves_existing_header(self) -> None:
        """preserve_existing=True (default) → existing header НЕ перезаписывается."""
        op = CorrelationIdentifierProcessor()
        ex = _exchange({}, headers={HEADER_CORRELATION_ID: "upstream-cid-123"})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_CORRELATION_ID) == "upstream-cid-123"
        assert ex.meta.correlation_id == "upstream-cid-123"
        assert op.stats()["preserved"] == 1

    @pytest.mark.asyncio
    async def test_custom_id_factory(self) -> None:
        """id_factory передан → используется."""
        counter = {"n": 0}

        def factory() -> str:
            counter["n"] += 1
            return f"cid-{counter['n']:04d}"

        op = CorrelationIdentifierProcessor(id_factory=factory)
        ex1 = _exchange({})
        await op.process(ex1, _ctx())
        ex2 = _exchange({})
        await op.process(ex2, _ctx())
        assert ex1.in_message.get_header(HEADER_CORRELATION_ID) == "cid-0001"
        assert ex2.in_message.get_header(HEADER_CORRELATION_ID) == "cid-0002"


# ── MessageExpirationProcessor ──────────────────────────────────────


class TestMessageExpiration:
    @pytest.mark.asyncio
    async def test_not_expired_sets_header(self) -> None:
        """TTL в будущем → header set, exchange НЕ stopped."""
        op = MessageExpirationProcessor(ttl_seconds=300)
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header("expiration") is not None
        assert ex.error is None
        assert op.stats()["kept"] == 1
        # remaining_ms should be > 0 (close to 300000)
        remaining = ex.get_property("message_expiration.remaining_ms")
        assert remaining is not None and remaining > 0

    @pytest.mark.asyncio
    async def test_already_expired_dispatches_and_stops(self) -> None:
        """Resolver возвращает past datetime → expired + dispatcher вызван + stop."""
        dispatched: list[tuple[str, Exchange]] = []

        def dispatcher(action: str, ex: Exchange) -> None:
            dispatched.append((action, ex))

        past = datetime.now(tz=timezone.utc) - timedelta(seconds=10)
        op = MessageExpirationProcessor(
            expiration_resolver=lambda ex: past,
            on_expired_action="dlq",
            action_dispatcher=dispatcher,
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.get_property("message_expiration.expired") is True
        assert op.stats()["expired"] == 1
        # Dispatcher called
        assert len(dispatched) == 1
        assert dispatched[0][0] == "dlq"
        # handle_processor_error: stop() does not set error
        assert ex.error is None

    @pytest.mark.asyncio
    async def test_ttl_validation(self) -> None:
        """ttl < 0 → ValueError at construction."""
        with pytest.raises(ValueError, match="ttl_seconds must be >= 0"):
            MessageExpirationProcessor(ttl_seconds=-1)

    def test_requires_ttl_or_resolver(self) -> None:
        """Ни ttl, ни resolver → ValueError."""
        with pytest.raises(ValueError, match="ttl_seconds or expiration_resolver"):
            MessageExpirationProcessor()


# ── RedeliveryPolicyProcessor ───────────────────────────────────────


class TestRedeliveryPolicy:
    @pytest.mark.asyncio
    async def test_first_attempt(self) -> None:
        """Первый attempt: counter=1, no exhaustion."""
        op = RedeliveryPolicyProcessor(
            max_attempts=3,
            initial_delay_s=0.01,  # minimal for test
        )
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 1
        assert ex.in_message.get_header("redelivered") is True
        assert ex.get_property("redelivery_policy.attempt") == 1
        assert op.stats()["retried"] == 1
        assert op.stats()["exhausted"] == 0

    @pytest.mark.asyncio
    async def test_exponential_backoff(self) -> None:
        """3 attempts на одном exchange: delays = 1, 2, 4 (initial=1, mult=2)."""
        op = RedeliveryPolicyProcessor(
            max_attempts=3,
            initial_delay_s=1.0,
            backoff_multiplier=2.0,
            max_delay_s=100.0,
        )
        ex = _exchange({})  # same exchange — state persists
        delays: list[float] = []
        for _ in range(3):
            await op.process(ex, _ctx())
            delays.append(ex.get_property("redelivery_policy.next_delay_s"))
        # Exponential: 1.0, 2.0, 4.0
        assert delays == [1.0, 2.0, 4.0]
        assert ex.in_message.get_header(HEADER_REDELIVERY_COUNT) == 3

    @pytest.mark.asyncio
    async def test_exhausted_after_max_attempts(self) -> None:
        """After max_attempts → exhausted + dispatcher called."""
        dispatched: list[tuple[str, Exchange]] = []

        def dispatcher(action: str, ex: Exchange) -> None:
            dispatched.append((action, ex))

        op = RedeliveryPolicyProcessor(
            max_attempts=2,
            initial_delay_s=0.01,
            on_exhausted_action="dlq",
            action_dispatcher=dispatcher,
        )
        ex = _exchange({})  # shared exchange
        # 3 attempts: 1, 2 (retried), 3 (exhausted)
        for _ in range(3):
            await op.process(ex, _ctx())
        assert op.stats()["retried"] == 2
        assert op.stats()["exhausted"] == 1
        assert len(dispatched) == 1
        assert dispatched[0][0] == "dlq"
        assert ex.get_property("redelivery_policy.exhausted") is True

    def test_max_attempts_validation(self) -> None:
        """max_attempts < 1 → ValueError."""
        with pytest.raises(ValueError, match="max_attempts must be >= 1"):
            RedeliveryPolicyProcessor(max_attempts=0)


# ── ReturnAddressProcessor ──────────────────────────────────────────


class TestReturnAddress:
    @pytest.mark.asyncio
    async def test_static_address(self) -> None:
        """Static return_address → header set."""
        op = ReturnAddressProcessor(return_address="kafka:replies")
        ex = _exchange({})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_RETURN_ADDRESS) == "kafka:replies"
        assert op.stats()["resolved"] == 1

    @pytest.mark.asyncio
    async def test_preserves_existing(self) -> None:
        """Existing return_address в header → preserve, no overwrite."""
        op = ReturnAddressProcessor(return_address="kafka:replies")
        ex = _exchange({}, headers={HEADER_RETURN_ADDRESS: "kafka:custom"})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_RETURN_ADDRESS) == "kafka:custom"
        assert op.stats()["resolved"] == 0

    @pytest.mark.asyncio
    async def test_dynamic_resolver(self) -> None:
        """Dynamic address_resolver → используется, async awaited."""

        async def resolve(ex: Exchange) -> str:
            await asyncio.sleep(0)
            return f"kafka:{ex.in_message.body['topic']}"

        op = ReturnAddressProcessor(address_resolver=resolve)
        ex = _exchange({"topic": "user-events"})
        await op.process(ex, _ctx())
        assert ex.in_message.get_header(HEADER_RETURN_ADDRESS) == "kafka:user-events"
        assert op.stats()["resolved"] == 1

    def test_requires_address_or_resolver(self) -> None:
        """Ни address, ни resolver → ValueError."""
        with pytest.raises(ValueError, match="return_address or address_resolver"):
            ReturnAddressProcessor()
