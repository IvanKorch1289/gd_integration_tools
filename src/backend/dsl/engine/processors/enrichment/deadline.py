from __future__ import annotations
"""S61 W2 — deadline.py part of enrichment decomp.

Classes: DeadlineProcessor.

deadline enforcement.
"""

import time
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class DeadlineProcessor(BaseProcessor):
    """Устанавливает дedline для pipeline — проверяется последующими процессорами.

    Usage::
        .deadline(timeout_seconds=30)
        # ... дальнейшие процессоры проверяют exchange.properties['_deadline_at']
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        fail_on_exceed: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"deadline({timeout_seconds}s)")
        self._timeout = timeout_seconds
        self._fail = fail_on_exceed

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        now = time.monotonic()
        existing = exchange.properties.get("_deadline_at")
        if existing is not None and isinstance(existing, (int, float)):
            if now >= existing:
                if self._fail:
                    exchange.fail(f"Deadline exceeded by {now - existing:.2f}s")
                return
            return
        exchange.set_property("_deadline_at", now + self._timeout)
        exchange.set_property("_deadline_set_at", now)

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {}
        if self._timeout != 30.0:
            spec["timeout_seconds"] = self._timeout
        if self._fail is not True:
            spec["fail_on_exceed"] = self._fail
        return {"deadline": spec}

