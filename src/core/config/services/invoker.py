"""Конфигурация Invoker и TaskIQ (W22 F.2 C1-C3).

Секции:

* ``invoker:`` — параметры главного Gateway вызовов:
  ``default_mode``, ``default_timeout_seconds``, ``allowed_modes``,
  ``streaming_chunk_buffer_size`` (для STREAMING).
* ``taskiq:`` — параметры брокера фоновых задач (используется
  ``InvocationMode.ASYNC_QUEUE``): ``enabled``, ``broker_url``,
  ``result_backend_url``, ``queue_name``.

Настройки опциональны (значения по умолчанию покрывают dev_light).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = (
    "InvokerSettings",
    "TaskiqSettings",
    "invoker_settings",
    "taskiq_settings",
)


# Перечислим режимы как Literal — при изменении :class:`InvocationMode`
# нужно синхронизировать (тест-контракт обеспечит проверка).
_InvocationModeName = Literal[
    "sync",
    "async-api",
    "async-queue",
    "deferred",
    "background",
    "streaming",
]


class InvokerSettings(BaseSettingsWithLoader):
    """Параметры главного Invoker Gateway."""

    yaml_group: ClassVar[str] = "invoker"
    model_config = SettingsConfigDict(env_prefix="INVOKER_", extra="forbid")

    default_mode: _InvocationModeName = Field(
        default="sync",
        description="Режим по умолчанию для вызовов без явного mode.",
    )
    default_timeout_seconds: float | None = Field(
        default=None,
        ge=0,
        description=(
            "Таймаут SYNC по умолчанию (секунды). ``None`` = без таймаута; "
            "переопределяется per-call через InvocationRequest.timeout."
        ),
    )
    allowed_modes: tuple[_InvocationModeName, ...] = Field(
        default=(
            "sync",
            "async-api",
            "async-queue",
            "deferred",
            "background",
            "streaming",
        ),
        description=(
            "Подмножество режимов, разрешённых на этом профиле. "
            "Используется ResilienceCoordinator/admission control для "
            "блокировки тяжёлых режимов на dev_light."
        ),
    )
    streaming_chunk_buffer_size: int = Field(
        default=64,
        ge=1,
        le=8192,
        description="Размер буфера chunks при STREAMING (для backpressure).",
    )


class TaskiqSettings(BaseSettingsWithLoader):
    """Параметры брокера TaskIQ (используется ASYNC_QUEUE)."""

    yaml_group: ClassVar[str] = "taskiq"
    model_config = SettingsConfigDict(env_prefix="TASKIQ_", extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Включить TaskIQ-брокер. На dev_light по умолчанию ``False`` — "
            "ASYNC_QUEUE возвращает ERROR с понятной диагностикой."
        ),
    )
    broker_url: str = Field(
        default="memory://",
        description=(
            "URL брокера: ``memory://`` (in-process), ``redis://...``, "
            "``amqp://...``."
        ),
    )
    result_backend_url: str = Field(
        default="memory://",
        description="URL backend'а результатов (для polling-режима).",
    )
    queue_name: str = Field(
        default="invocations",
        description="Имя очереди для фоновых invocation-задач.",
    )


invoker_settings = InvokerSettings()
"""Глобальные настройки Invoker."""

taskiq_settings = TaskiqSettings()
"""Глобальные настройки TaskIQ."""
