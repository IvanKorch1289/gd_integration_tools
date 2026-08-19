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
    """DSL processor для записи структурированных логов из pipeline.

    Использует ``get_logger_factory`` facade для получения logger'а.
    Поддерживает стандартные уровни: debug, info, warning, error, critical.
    """

    def __init__(self, level: str, message: str) -> None:
        """Создать процессор с фиксированным уровнем и сообщением.

        Args:
            level: Уровень логирования (``debug|info|warning|error|critical``).
            message: Текст сообщения для логирования.

        Raises:
            ValueError: Если ``level`` не из допустимого набора.

        """
        super().__init__(name="infra_log_write")
        if level not in ("debug", "info", "warning", "error", "critical"):
            raise ValueError(f"Invalid log level: {level}")
        self.level = level
        self.message = message

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Записать сообщение в лог через facade logger.

        Args:
            exchange: Текущий exchange (не используется, для совместимости API).
            context: Контекст исполнения workflow (не используется).

        Notes:
            ``exchange`` и ``context`` принимаются для совместимости с
            базовым ``BaseProcessor.process`` API, но не используются —
            процессор stateless и не модифицирует exchange.

        """
        from src.backend.core.di.providers.infrastructure_locator import (
            get_logger_factory as _get_logger_factory_fn,
        )

        logger = _get_logger_factory_fn()("dsl.infra_log")
        log_fn = getattr(logger, self.level)
        log_fn(self.message)
