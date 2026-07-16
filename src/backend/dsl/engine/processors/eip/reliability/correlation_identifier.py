"""S175 Phase 2: CorrelationIdentifierProcessor (full implementation).

Camel EIP: https://camel.apache.org/components/latest/eips/correlation-identifier.html

Phase 2 migration: класс полностью перенесён из ``_legacy.py``.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Callable, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import (
    BaseProcessor,
    handle_processor_error,
)
from src.backend.dsl.engine.processors.eip.reliability._legacy import HEADER_CORRELATION_ID

__all__ = ("CorrelationIdentifierProcessor", "HEADER_CORRELATION_ID", "IdFactory")

IdFactory = Callable[[], str]


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
        """Применяет correlation_id политику: preserve existing или generate new."""
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

    def stats(self) -> dict[str, int]:
        """Возвращает счётчики generated/preserved под lock."""
        with self._lock:
            return {"generated": self._generated, "preserved": self._preserved}

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализует конфиг процессора в JSON-Schema spec."""
        return {
            "type": "correlation_identifier",
            "preserve_existing": self._preserve,
            "header_name": self._header_name,
        }
