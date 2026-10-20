"""DSL processor ``infra_log`` (Sprint 170 M2 Phase 2).

Log write через facade logger::

    - infra_log_write:
        level: info
        message: "Processing order ${properties.order_id}"

Cycle 169 (DSL_AUDIT_CACHE_LOGGING_2026-10-20 §2.2): интерполяция
``${body.x}`` / ``${properties.foo}`` / ``${result.bar}`` / ``${header.X-Foo}``
через ``_resolve`` helper. Раньше ``message`` логировался literal-строкой
без подстановки — противоречило документации.
"""

from __future__ import annotations

import re
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

    Cycle 169: ``message`` поддерживает ``${...}`` интерполяцию через
    ``_resolve`` (см. ``processors/entity/_resolve_helper.py``).
    Поддерживаемые namespaces: ``body.``, ``properties.``, ``result.``,
    ``header.``.
    """

    _PLACEHOLDER_RE = re.compile(r"\$\{([^}]+)\}")

    def __init__(self, level: str, message: str) -> None:
        """Создать процессор с фиксированным уровнем и сообщением.

        Args:
            level: Уровень логирования (``debug|info|warning|error|critical``).
            message: Текст сообщения; поддерживает ``${namespace.path}``
                placeholders (cycle 169).

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

        Cycle 169: интерполирует ``${...}`` placeholders через
        ``_resolve`` helper (body/properties/result/header namespaces).
        Если placeholder не резолвится — остаётся literal ``${...}``
        (graceful degradation).

        Args:
            exchange: Текущий exchange (для placeholder resolution).
            context: Контекст исполнения workflow (для совместимости API,
                сейчас не используется — процессор stateless).

        """
        from src.backend.core.di.providers.infrastructure_locator import (
            get_logger_factory as _get_logger_factory_fn,
        )
        from src.backend.dsl.engine.processors.entity._resolve_helper import (
            _resolve as _resolve_expr,
        )

        logger = _get_logger_factory_fn()("dsl.infra_log")
        log_fn = getattr(logger, self.level)

        def _sub(m: re.Match[str]) -> str:
            expr = m.group(1)
            resolved = _resolve_expr(exchange, expr)
            return str(resolved) if resolved is not None else m.group(0)

        rendered = self._PLACEHOLDER_RE.sub(_sub, self.message)
        log_fn(rendered)
