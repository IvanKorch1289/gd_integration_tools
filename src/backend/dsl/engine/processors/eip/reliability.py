"""EIP reliability patterns: Redelivery, Expiration, Correlation ID, Return Address (S56 W3).

Apache Camel EIP catalog (reliability / routing-metadata):

* :class:`RedeliveryPolicyProcessor` — Redelivery: https://camel.apache.org/components/latest/eips/redelivery.html
  Retry policy для failed message delivery с exponential backoff и DLQ-routing
  после N attempts.

* :class:`MessageExpirationProcessor` — Message Expiration: https://camel.apache.org/components/latest/eips/message-expiration.html
  TTL на message (PEX — per-message expiration). Expired messages drop
  с optional on_expired_action.

* :class:`CorrelationIdentifierProcessor` — Correlation Identifier: https://camel.apache.org/components/latest/eips/correlation-identifier.html
  Управление ``correlation_id`` header: explicit set, propagate from upstream
  message, или generate через factory (UUID4 / ULID / snowflake).

* :class:`ReturnAddressProcessor` — Return Address: https://camel.apache.org/components/latest/eips/return-address.html
  Capture original ``reply_to`` endpoint при request-reply pattern,
  attach к headers для downstream callback routing.

Все процессоры — :class:`BaseProcessor` для inline-использования в DSL.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

__all__ = (
    "CorrelationIdentifierProcessor",
    "MessageExpirationProcessor",
    "RedeliveryPolicyProcessor",
    "ReturnAddressProcessor",
)

_log = get_logger(__name__)


# Header constants — стандартные имена (JMS-style / Camel conventions).
HEADER_CORRELATION_ID = "correlation_id"
HEADER_MESSAGE_ID = "message_id"
HEADER_EXPIRATION = "expiration"  # millis-since-epoch (JMS-style) или ISO 8601
HEADER_REDELIVERED = "redelivered"
HEADER_REDELIVERY_COUNT = "redelivery_count"
HEADER_RETURN_ADDRESS = "return_address"  # reply-to endpoint URI


# Type aliases
IdFactory = Callable[[], str]
ExpirationResolver = Callable[
    [Exchange[Any]], datetime | None | Awaitable[datetime | None]
]
RedeliveryAttempt = tuple[int, float]  # (attempt_number, delay_seconds)


# ── CorrelationIdentifierProcessor ──────────────────────────────────


class CorrelationIdentifierProcessor(BaseProcessor):
    """Управление correlation_id header (Camel Correlation Identifier).

    Args:
        id_factory: callable → str (default UUID4). Можно подменить на
            ULID/snowflake factory для sortable IDs.
        preserve_existing: если True (default) — header уже set НЕ перезаписывается.
        header_name: имя header (default ``correlation_id``).
        name: имя процессора.

    Side effect: ``exchange.in_message.set_header(correlation_id, ...)``.
    Также синхронизирует ``exchange.meta.correlation_id`` (для observability/tracing).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        id_factory: IdFactory | None = None,
        *,
        preserve_existing: bool = True,
        header_name: str = HEADER_CORRELATION_ID,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "correlation_identifier")
        self._factory = id_factory or (lambda: str(uuid.uuid4()))
        self._preserve = preserve_existing
        self._header_name = header_name
        self._lock = threading.Lock()
        self._generated = 0
        self._preserved = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        existing = exchange.in_message.get_header(self._header_name)

        if existing and self._preserve:
            new_id = str(existing)
            with self._lock:
                self._preserved += 1
        else:
            new_id = self._factory()
            exchange.in_message.set_header(self._header_name, new_id)
            with self._lock:
                self._generated += 1

        # Sync to meta (для OTel/tracing — correlation_id в span context)
        exchange.meta.correlation_id = new_id
        _log.debug("CorrelationIdentifier: %s (preserved=%s)", new_id, bool(existing))

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"generated": self._generated, "preserved": self._preserved}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "correlation_identifier",
            "preserve_existing": self._preserve,
            "header_name": self._header_name,
        }


# ── MessageExpirationProcessor ──────────────────────────────────────


class MessageExpirationProcessor(BaseProcessor):
    """TTL / expiration на message (Camel Message Expiration).

    Args:
        ttl_seconds: int — фиксированный TTL от текущего момента.
        expiration_resolver: callable(exchange) → datetime (absolute expiration)
            или None. Если задан — имеет приоритет над ``ttl_seconds``.
        on_expired_action: имя action для expired messages (default "dlq").
        action_dispatcher: callable(action_name, exchange) → None/Awaitable.
            Если None — expired message просто stopped (drop).
        header_name: имя header (default ``expiration``).
        time_source: callable → datetime (default datetime.now UTC).
            Test-friendly: можно подменить на deterministic clock.
        name: имя процессора.

    Side effect: expired messages — ``exchange.stop()`` + optional dispatch.
    """

    side_effect: ClassVar[SideEffectKind] = (
        SideEffectKind.STATEFUL
    )  # tracks state (current/expiring)

    def __init__(  # noqa: PLR0913
        self,
        *,
        ttl_seconds: int | None = None,
        expiration_resolver: ExpirationResolver | None = None,
        on_expired_action: str = "dlq",
        action_dispatcher: Callable[[str, Exchange[Any]], Any | Awaitable[Any]]
        | None = None,
        header_name: str = HEADER_EXPIRATION,
        time_source: Callable[[], datetime] | None = None,
        name: str | None = None,
    ) -> None:
        if ttl_seconds is None and expiration_resolver is None:
            raise ValueError(
                "MessageExpirationProcessor: either ttl_seconds or expiration_resolver required"
            )
        if ttl_seconds is not None and ttl_seconds < 0:
            raise ValueError("ttl_seconds must be >= 0")
        super().__init__(name=name or "message_expiration")
        self._ttl_seconds = ttl_seconds
        self._resolver = expiration_resolver
        self._on_expired = on_expired_action
        self._dispatcher = action_dispatcher
        self._header_name = header_name
        self._time_source = time_source or (lambda: datetime.now(tz=timezone.utc))
        self._lock = threading.Lock()
        self._expired_count = 0
        self._kept_count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Compute expiration deadline
        exp: datetime | None = None
        if self._resolver is not None:
            resolved = self._resolver(exchange)
            if asyncio.iscoroutine(resolved):
                resolved = await resolved
            if isinstance(resolved, datetime):
                exp = resolved
        else:
            assert self._ttl_seconds is not None
            exp = self._time_source() + timedelta(seconds=self._ttl_seconds)

        # Store expiration header (JMS-style: epoch millis)
        if exp is not None:
            exp_epoch_ms = int(exp.timestamp() * 1000)
            exchange.in_message.set_header(self._header_name, exp_epoch_ms)

        # Check if already expired
        now = self._time_source()
        if exp is not None and now >= exp:
            _log.debug("MessageExpiration: EXPIRED, dispatch to %s", self._on_expired)
            with self._lock:
                self._expired_count += 1
            exchange.set_property("message_expiration.expired", True)
            if self._dispatcher is not None:
                result = self._dispatcher(self._on_expired, exchange)
                if asyncio.iscoroutine(result):
                    await result
            exchange.stop()
        else:
            with self._lock:
                self._kept_count += 1
            remaining_ms = int((exp - now).total_seconds() * 1000) if exp else None
            exchange.set_property("message_expiration.remaining_ms", remaining_ms)
            _log.debug("MessageExpiration: not expired, remaining=%sms", remaining_ms)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"expired": self._expired_count, "kept": self._kept_count}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "message_expiration",
            "ttl_seconds": self._ttl_seconds,
            "on_expired_action": self._on_expired,
        }


# ── RedeliveryPolicyProcessor ───────────────────────────────────────


class RedeliveryPolicyProcessor(BaseProcessor):
    """Retry-with-backoff policy для failed message delivery (Camel Redelivery).

    Args:
        max_attempts: максимум retries (default 3).
        initial_delay_s: начальная задержка (default 1.0).
        backoff_multiplier: factor для exponential backoff (default 2.0).
        max_delay_s: cap на delay (default 60.0).
        redelivery_header: имя header для redelivery counter (default
            ``redelivery_count``).
        on_exhausted_action: куда dispatchить после N failed attempts
            (default "dlq").
        action_dispatcher: callable(action_name, exchange) → None/Awaitable.
            Если None — exchange.stop() после exhausted.
        name: имя процессора.

    Логика: на каждом exchange.process() инкрементирует redelivery_count
    в header. Если count <= max_attempts — delay + retry. Иначе — exhausted.

    Это meta-processor: не выполняет downstream pipeline, только
    обновляет headers + применяет delay/dispatch решения.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.STATEFUL

    def __init__(  # noqa: PLR0913
        self,
        *,
        max_attempts: int = 3,
        initial_delay_s: float = 1.0,
        backoff_multiplier: float = 2.0,
        max_delay_s: float = 60.0,
        redelivery_header: str = HEADER_REDELIVERY_COUNT,
        on_exhausted_action: str = "dlq",
        action_dispatcher: Callable[[str, Exchange[Any]], Any | Awaitable[Any]]
        | None = None,
        name: str | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        if initial_delay_s < 0:
            raise ValueError("initial_delay_s must be >= 0")
        if backoff_multiplier < 1.0:
            raise ValueError("backoff_multiplier must be >= 1.0")
        super().__init__(name=name or "redelivery_policy")
        self._max_attempts = max_attempts
        self._initial_delay = initial_delay_s
        self._backoff = backoff_multiplier
        self._max_delay = max_delay_s
        self._header = redelivery_header
        self._on_exhausted = on_exhausted_action
        self._dispatcher = action_dispatcher
        self._lock = threading.Lock()
        self._retried = 0
        self._exhausted = 0

    def _compute_delay(self, attempt: int) -> float:
        """Exponential backoff с cap."""
        delay = self._initial_delay * (self._backoff ** (attempt - 1))
        return min(delay, self._max_delay)

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        attempt_raw = exchange.in_message.get_header(self._header)
        if attempt_raw is None:
            attempt = 1
            exchange.in_message.set_header(self._header, 1)
        else:
            try:
                attempt = int(attempt_raw) + 1
            except (TypeError, ValueError):
                attempt = 1
            exchange.in_message.set_header(self._header, attempt)

        exchange.in_message.set_header(HEADER_REDELIVERED, True)

        if attempt > self._max_attempts:
            _log.warning(
                "RedeliveryPolicy: exhausted after %d attempts, dispatch to %s",
                attempt - 1,
                self._on_exhausted,
            )
            with self._lock:
                self._exhausted += 1
            exchange.set_property("redelivery_policy.exhausted", True)
            if self._dispatcher is not None:
                result = self._dispatcher(self._on_exhausted, exchange)
                if asyncio.iscoroutine(result):
                    await result
            exchange.stop()
            return

        delay = self._compute_delay(attempt)
        exchange.set_property("redelivery_policy.next_delay_s", delay)
        exchange.set_property("redelivery_policy.attempt", attempt)
        with self._lock:
            self._retried += 1
        _log.debug(
            "RedeliveryPolicy: attempt=%d/%d, delay=%.2fs",
            attempt,
            self._max_attempts,
            delay,
        )
        # Optional: apply delay (only if > 0 and not in synchronous mode)
        if delay > 0:
            await asyncio.sleep(delay)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"retried": self._retried, "exhausted": self._exhausted}

    def to_spec(self) -> dict[str, Any] | None:
        return {
            "type": "redelivery_policy",
            "max_attempts": self._max_attempts,
            "initial_delay_s": self._initial_delay,
            "backoff_multiplier": self._backoff,
            "max_delay_s": self._max_delay,
        }


# ── ReturnAddressProcessor ──────────────────────────────────────────


class ReturnAddressProcessor(BaseProcessor):
    """Capture reply-to / return address (Camel Return Address).

    Args:
        return_address: статический endpoint URI (e.g., ``kafka:replies``,
            ``http://api.example.com/callback``).
        address_resolver: callable(exchange) → str (для dynamic address).
            Если задан — имеет приоритет над ``return_address``.
        header_name: имя header (default ``return_address``).
        name: имя процессора.

    Использование (request-reply pattern)::

        .process(ReturnAddressProcessor(
            return_address="kafka:customer-replies",
        ))
        .process(SendToProcessor(endpoint="kafka:customer-requests"))

    Downstream consumer читает ``return_address`` header для callback routing.
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE

    def __init__(
        self,
        return_address: str | None = None,
        *,
        address_resolver: Callable[[Exchange[Any]], str | Awaitable[str]] | None = None,
        header_name: str = HEADER_RETURN_ADDRESS,
        name: str | None = None,
    ) -> None:
        if return_address is None and address_resolver is None:
            raise ValueError(
                "ReturnAddressProcessor: either return_address or address_resolver required"
            )
        super().__init__(name=name or "return_address")
        self._static_address = return_address
        self._resolver = address_resolver
        self._header_name = header_name
        self._lock = threading.Lock()
        self._resolved_count = 0

    @handle_processor_error
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        # Preserve existing return address if already set (chained requests)
        existing = exchange.in_message.get_header(self._header_name)
        if existing:
            _log.debug("ReturnAddress: preserve existing %s", existing)
            return

        if self._resolver is not None:
            addr = self._resolver(exchange)
            if asyncio.iscoroutine(addr):
                addr = await addr
        else:
            addr = self._static_address

        addr_str = str(addr)
        exchange.in_message.set_header(self._header_name, addr_str)
        with self._lock:
            self._resolved_count += 1
        _log.debug("ReturnAddress: set %s", addr_str)

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"resolved": self._resolved_count}

    def to_spec(self) -> dict[str, Any] | None:
        return {"type": "return_address", "return_address": self._static_address}
