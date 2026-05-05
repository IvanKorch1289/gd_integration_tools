"""Универсальные неспецифические процессоры: shadow mode, bulkhead,
lineage, SSE, schema validation, A/B test router, feature flag guard.

Эти процессоры не привязаны к банковскому домену и полезны в любом
интеграционном сценарии.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, Callable

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange
from src.dsl.engine.processors.base import BaseProcessor, run_sub_processors

__all__ = (
    "ShadowModeProcessor",
    "BulkheadProcessor",
    "LineageTrackerProcessor",
    "SseSourceProcessor",
    "SchemaValidateProcessor",
    "AbTestRouterProcessor",
    "FeatureFlagGuardProcessor",
)

logger = logging.getLogger("dsl.generic")


class ShadowModeProcessor(BaseProcessor):
    """Исполняет вложенные процессоры в «теневом режиме» — без side effects.

    Любые write-операции (HTTP POST/PUT, DB insert, file write) в ветке
    получают пометку `exchange.properties["shadow_mode"] = True`; процессоры,
    её поддерживающие, должны пропускать побочные эффекты и только логировать.

    Используется для канареечного тестирования пайплайна на продовом трафике.
    """

    def __init__(self, processors: list[BaseProcessor]) -> None:
        super().__init__(name="shadow_mode")
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        was_shadow = exchange.get_property("shadow_mode", False)
        exchange.set_property("shadow_mode", True)
        try:
            await run_sub_processors(self._processors, exchange, context)
        finally:
            exchange.set_property("shadow_mode", was_shadow)


class BulkheadProcessor(BaseProcessor):
    """Ограничивает одновременное выполнение вложенной ветки на уровне всего процесса.

    Защищает внешних провайдеров от перегрузки при всплеске трафика:
    если concurrency исчерпан, новые запросы ждут или получают ошибку.

    Реализован через asyncio.Semaphore — общий на имя bulkhead'а.
    """

    _semaphores: dict[str, asyncio.Semaphore] = {}

    def __init__(
        self,
        name: str,
        limit: int,
        processors: list[BaseProcessor],
        wait: bool = True,
        timeout: float | None = None,
    ) -> None:
        super().__init__(name=f"bulkhead:{name}")
        if limit < 1:
            raise ValueError("limit должен быть >= 1")
        self.bulkhead_name = name
        self.limit = limit
        self._processors = processors
        self.wait = wait
        self.timeout = timeout

    def _get_semaphore(self) -> asyncio.Semaphore:
        sem = self._semaphores.get(self.bulkhead_name)
        if sem is None or sem._value > self.limit:  # type: ignore[attr-defined]
            sem = asyncio.Semaphore(self.limit)
            self._semaphores[self.bulkhead_name] = sem
        return sem

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        sem = self._get_semaphore()
        if not self.wait and sem.locked():
            raise RuntimeError(f"Bulkhead '{self.bulkhead_name}' исчерпан")

        acquire = sem.acquire()
        if self.timeout:
            await asyncio.wait_for(acquire, timeout=self.timeout)
        else:
            await acquire
        try:
            await run_sub_processors(self._processors, exchange, context)
        finally:
            sem.release()


class LineageTrackerProcessor(BaseProcessor):
    """Фиксирует происхождение данных: какой pipeline и processor положил значение.

    В `exchange.properties["_lineage"]` дописывается запись
    {"route_id": ..., "processor": ..., "at": ...} каждый раз, когда
    пайплайн проходит через этот процессор.

    Упрощает data governance: по результату можно восстановить путь.
    """

    def __init__(self, tag: str = "step") -> None:
        super().__init__(name=f"lineage:{tag}")
        self.tag = tag

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        lineage: list[dict[str, Any]] = exchange.get_property("_lineage", [])
        lineage.append(
            {
                "route_id": getattr(context.meta, "route_id", None)
                if context.meta
                else None,
                "tag": self.tag,
            }
        )
        exchange.set_property("_lineage", lineage)


class SseSourceProcessor(BaseProcessor):
    """Source-процессор для Server-Sent Events.

    Сам процессор — маркер; реальное подключение к SSE-stream'у
    делегируется в сервис через action.
    """

    def __init__(self, url: str, event_types: list[str] | None = None) -> None:
        super().__init__(name=f"sse:{url}")
        self.url = url
        self.event_types = event_types or []

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        exchange.set_property("sse_url", self.url)
        exchange.set_property("sse_event_types", self.event_types)
        exchange.set_property("dispatch_action", "sse.consume")


class SchemaValidateProcessor(BaseProcessor):
    """Валидация body по JSON Schema (Draft 2020-12).

    Использует библиотеку jsonschema, если она установлена; иначе —
    минимальная проверка (type + required). Для строгих контрактов
    рекомендуется переключиться на Pydantic через `.validate()`.
    """

    def __init__(self, schema: dict[str, Any]) -> None:
        super().__init__(name="schema_validate")
        self.schema = schema
        try:
            import jsonschema  # noqa: F401

            self._strict = True
        except ImportError:
            self._strict = False

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if self._strict:
            import jsonschema

            jsonschema.validate(instance=body, schema=self.schema)
            return

        # Fallback: минимальная проверка type + required
        expected = self.schema.get("type")
        if expected == "object" and not isinstance(body, dict):
            raise ValueError(f"body must be object, got {type(body).__name__}")
        required = self.schema.get("required") or []
        if isinstance(body, dict):
            missing = [k for k in required if k not in body]
            if missing:
                raise ValueError(f"Missing required fields: {missing}")


class AbTestRouterProcessor(BaseProcessor):
    """Стабильная маршрутизация X% трафика на вариант B.

    Хэш ключа (по умолчанию — идентификатор exchange) mod 100 сравнивается
    с `split_percent`: если меньше — вариант B, иначе — вариант A.

    Стабильно: один и тот же ключ всегда попадает в одну ветку.
    """

    def __init__(
        self,
        variant_a: list[BaseProcessor],
        variant_b: list[BaseProcessor],
        split_percent: int = 50,
        key_fn: Callable[[Exchange[Any]], str] | None = None,
    ) -> None:
        super().__init__(name="ab_test")
        if not 0 <= split_percent <= 100:
            raise ValueError("split_percent: 0..100")
        self._a = variant_a
        self._b = variant_b
        self.split_percent = split_percent
        self._key_fn = key_fn or (
            lambda ex: str(getattr(ex.meta, "exchange_id", "") or id(ex))
        )

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        key = self._key_fn(exchange)
        bucket = (
            int(hashlib.sha1(key.encode(), usedforsecurity=False).hexdigest(), 16) % 100
        )
        variant = "B" if bucket < self.split_percent else "A"
        exchange.set_property("ab_variant", variant)
        branch = self._b if variant == "B" else self._a
        await run_sub_processors(branch, exchange, context)


class FeatureFlagGuardProcessor(BaseProcessor):
    """Пропускает вложенную ветку только если feature-flag включен.

    Источник флагов — callable `resolver(flag_name) -> bool`.
    Если флаг выключен, ветка пропускается (no-op), exchange не меняется.
    """

    def __init__(
        self,
        flag: str,
        processors: list[BaseProcessor],
        resolver: Callable[[str], bool] | None = None,
    ) -> None:
        super().__init__(name=f"ff_guard:{flag}")
        self.flag = flag
        self._processors = processors
        self._resolver = resolver

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        enabled = False
        if self._resolver:
            try:
                enabled = bool(self._resolver(self.flag))
            except Exception:  # noqa: BLE001
                logger.warning("feature flag resolver failed for %s", self.flag)
        else:
            flags = exchange.get_property("_feature_flags") or {}
            enabled = bool(flags.get(self.flag, False))

        if not enabled:
            return
        await run_sub_processors(self._processors, exchange, context)
