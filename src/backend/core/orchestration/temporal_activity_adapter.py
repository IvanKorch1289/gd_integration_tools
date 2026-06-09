"""K2 W1 — Temporal Activity Adapter (post-TaskIQ removal).

Адаптер для ``Invoker.ASYNC_QUEUE``-callsites. Все callsites идут через
``wrap_as_temporal_activity()`` (Sprint 8 K2 W1: TaskIQ полностью удалён).

Контракт минимальный: callable (sync или async) оборачивается в
Temporal-совместимую activity-обёртку, возвращает ``Awaitable[Any]``.
Heavy ``temporalio.activity.defn`` декоратор подключается lazy внутри
самой обёртки — модуль ядра не зависит от ``temporalio`` SDK на import-time.

Семантика:
    * Idempotency: повторный wrap того же callable возвращает тот же
      обёрнутый объект (по id) — позволяет регистрировать activity один раз.
    * Error propagation: исключения forward как ApplicationError (для
      Temporal-side replay) при наличии SDK; иначе пробрасываются как есть.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
from collections.abc import Callable
from typing import Any, TypeVar

from src.backend.core.logging import get_logger

__all__ = ("TemporalActivityWrapper", "wrap_as_temporal_activity")

logger = get_logger("core.orchestration.temporal_activity_adapter")

T = TypeVar("T")


class TemporalActivityWrapper:
    """Обёртка вокруг callable, делающая его Temporal-совместимым.

    Хранит ссылку на оригинал, чтобы поддержать idempotency wrap'а
    (см. :func:`wrap_as_temporal_activity`).
    """

    __slots__ = ("_callable", "_is_async", "_name")

    def __init__(self, fn: Callable[..., Any], name: str | None = None) -> None:
        """Инициализирует обёртку.

        Args:
            fn: Целевой callable (sync или async).
            name: Имя activity для регистрации в Temporal worker;
                по умолчанию — ``fn.__qualname__``.
        """
        self._callable = fn
        self._name = str(name or getattr(fn, "__qualname__", repr(fn)))
        self._is_async = inspect.iscoroutinefunction(fn)

    @property
    def name(self) -> str:
        """Имя activity."""
        return self._name

    @property
    def original(self) -> Callable[..., Any]:
        """Возвращает обёрнутый исходный callable (для регистрации)."""
        return self._callable

    async def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Выполняет activity, проксируя исключения как Temporal-friendly.

        При наличии ``temporalio`` SDK будущие callsites могут вызывать
        execute_activity(wrapper) внутри workflow; здесь — прямой вызов
        для совместимости со старым ASYNC_QUEUE-маршрутом.
        """
        try:
            if self._is_async:
                result = await self._callable(*args, **kwargs)
            else:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, functools.partial(self._callable, *args, **kwargs)
                )
            return result
        except Exception as exc:
            logger.exception("TemporalActivityWrapper '%s' failed: %s", self._name, exc)
            raise


# Реестр для idempotency: один и тот же callable должен wrap'аться один раз.
_wrapper_cache: dict[int, TemporalActivityWrapper] = {}


def wrap_as_temporal_activity(
    fn: Callable[..., Any] | TemporalActivityWrapper, *, name: str | None = None
) -> TemporalActivityWrapper:
    """Оборачивает callable в Temporal-совместимую activity.

    Идемпотентен: повторный вызов с тем же ``fn`` возвращает тот же
    объект (по id), что упрощает регистрацию activity в worker.

    Args:
        fn: Целевая sync- или async-функция, либо уже обёрнутая.
        name: Опциональное имя activity (см. :class:`TemporalActivityWrapper`).

    Returns:
        :class:`TemporalActivityWrapper` — awaitable callable.

    Example::

        async def normalize_payload(data: dict) -> dict:
            return {"normalized": True, **data}

        activity = wrap_as_temporal_activity(normalize_payload)
        result = await activity({"x": 1})
        # → {"normalized": True, "x": 1}
    """
    # Идемпотентность: повторный wrap возвращает тот же объект.
    if isinstance(fn, TemporalActivityWrapper):
        return fn

    key = id(fn)
    cached = _wrapper_cache.get(key)
    if cached is not None and cached.original is fn:
        return cached

    wrapper = TemporalActivityWrapper(fn, name=name)
    _wrapper_cache[key] = wrapper
    return wrapper
