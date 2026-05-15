"""Конфигурация Invoker (W22 F.2 C1-C3).

Секции:

* ``invoker:`` — параметры главного Gateway вызовов:
  ``default_mode``, ``default_timeout_seconds``, ``allowed_modes``,
  ``streaming_chunk_buffer_size`` (для STREAMING).

Sprint 8 K2 W1: TaskiqSettings удалён вместе со всей TaskIQ-цепочкой.
Настройки опциональны (значения по умолчанию покрывают dev_light).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("InvokerSettings", "invoker_settings")


# Перечислим режимы как Literal — при изменении :class:`InvocationMode`
# нужно синхронизировать (тест-контракт обеспечит проверка).
_InvocationModeName = Literal[
    "sync", "async-api", "async-queue", "deferred", "background", "streaming"
]


class InvokerSettings(BaseSettingsWithLoader):
    """Параметры главного Invoker Gateway."""

    yaml_group: ClassVar[str] = "invoker"
    model_config = SettingsConfigDict(env_prefix="INVOKER_", extra="forbid")

    default_mode: _InvocationModeName = Field(
        default="sync", description="Режим по умолчанию для вызовов без явного mode."
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


invoker_settings = InvokerSettings()
"""Глобальные настройки Invoker."""
