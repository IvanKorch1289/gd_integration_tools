"""S175 Phase 2: MessageExpirationProcessor (full implementation).

Camel EIP: https://camel.apache.org/components/latest/eips/message-expiration.html

Phase 2 migration: класс полностью перенесён из ``_legacy.py``.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error
from src.backend.dsl.engine.processors.eip.reliability._legacy import (
    HEADER_EXPIRATION,
    HEADER_MESSAGE_ID,
    ExpirationResolver,
)

_log = get_logger(__name__)

__all__ = (
    "MessageExpirationProcessor",
    "ExpirationResolver",
    "HEADER_EXPIRATION",
    "HEADER_MESSAGE_ID",
)


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
        """Применяет expiration policy: drop expired messages или route via on_expired_action."""
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
        """Возвращает счётчики expired/kept под lock."""
        with self._lock:
            return {"expired": self._expired_count, "kept": self._kept_count}

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует конфиг процессора в JSON-Schema spec."""
        return {
            "type": "message_expiration",
            "ttl_seconds": self._ttl_seconds,
            "on_expired_action": self._on_expired,
        }
