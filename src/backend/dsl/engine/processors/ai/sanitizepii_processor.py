"""DSL процессор: Санитизация PII в LLM-входных данных (маскирование чувствительных данных)."""

from __future__ import annotations

import inspect
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


class SanitizePIIProcessor(BaseProcessor):
    """Маскирует PII в body перед передачей дальше."""

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name)

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        body = exchange.in_message.body
        if not isinstance(body, str):
            body = str(body)
        # S86 M2-#11 accelerated batch: DI provider.
        from src.backend.core.di.providers.cache import get_ai_sanitizer_provider

        sanitizer = get_ai_sanitizer_provider()  # instance (fix 2026-09-23)
        # Выбор ветки — по ТИПУ метода, а не по наличию атрибута: у моков
        # (``AsyncMock``) любой атрибут «есть», и ``hasattr``-проверка
        # уводила процессор в sync-ветку с awaitable-результатом →
        # «'coroutine' object has no attribute 'replacements'» и PII не
        # маскировалась (волна 36).
        #
        # * async-канон ``sanitize`` (legacy AIDataSanitizer) — если это
        #   coroutine-функция;
        # * sync-канон ``sanitize_text`` (Presidio-адаптер);
        # * результат может оказаться awaitable — тогда ждём его.
        sanitize = getattr(sanitizer, "sanitize", None)
        if sanitize is not None and inspect.iscoroutinefunction(sanitize):
            result = await sanitize(body)
        elif hasattr(sanitizer, "sanitize_text"):
            result = sanitizer.sanitize_text(body)
            if inspect.isawaitable(result):
                result = await result
        else:
            result = await sanitize(body)
        exchange.set_property("_pii_original", exchange.in_message.body)
        exchange.set_property("_pii_mapping", result.replacements)
        exchange.in_message.set_body(result.sanitized_text)

    def to_spec(self) -> dict[str, Any] | None:
        """Метод to_spec (см. signature)."""
        return {"sanitize_pii": {}}
