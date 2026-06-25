"""DSL processor ``infra_log`` (Sprint 170 M2 Phase 2).

Log write через facade logger::

    - infra_log_write:
        level: info
        message: "Processing order ${properties.order_id}"
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


@processor(
    "infra_log_write",
    namespace="infra",
    spec_schema={
        "type": "object",
        "properties": {
            "level": {"enum": ["debug", "info", "warning", "error", "critical"]},
            "message": {"type": "string"},
        },
        "required": ["level", "message"],
    },
    capabilities=("log.write",),
    meta={"tier": 1, "category": "infra"},
)
class InfraLogWriteProcessor(BaseProcessor):
    def __init__(self, level: str, message: str) -> None:
        super().__init__(name="infra_log_write")
        if level not in ("debug", "info", "warning", "error", "critical"):
            raise ValueError(f"Invalid log level: {level}")
        self.level = level
        self.message = message

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        from src.backend.core.di.providers.infrastructure_facade import (
            get_logger_factory as _get_logger_factory_fn,
        )
        logger = _get_logger_factory_fn()("dsl.infra_log")
        log_fn = getattr(logger, self.level)
        log_fn(self.message)
