"""W14.5 — настройки durable WatermarkStore.

Управляют выбором бэкенда (``memory`` для dev_light/тестов,
``postgres`` для prod) и поведением дебаунса персистов.

YAML-группа: ``watermark``. ENV-prefix: ``WATERMARK_``.
"""

from typing import ClassVar, Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("WatermarkSettings", "watermark_settings")


class WatermarkSettings(BaseSettingsWithLoader):
    """Конфигурация бэкенда :class:`WatermarkStore` (W14.5).

    Поля:

    * ``backend`` — ``memory`` (dev_light) или ``postgres`` (prod).
    * ``persist_min_interval`` — нижняя граница интервала между
      ``WatermarkStore.save`` (debounce, секунды wall-clock).
    """

    yaml_group: ClassVar[str] = "watermark"
    model_config = SettingsConfigDict(env_prefix="WATERMARK_", extra="forbid")

    backend: Literal["memory", "postgres"] = Field(
        default="memory",
        description=(
            "Бэкенд WatermarkStore: ``memory`` (in-process, dev_light/тесты) "
            "или ``postgres`` (durable, prod)."
        ),
        examples=["memory", "postgres"],
    )
    persist_min_interval: float = Field(
        default=1.0,
        ge=0.0,
        description=(
            "Минимальный интервал между сохранениями в store (секунды "
            "wall-clock). Защищает hot-path от частых I/O."
        ),
        examples=[0.0, 1.0, 5.0],
    )


watermark_settings = WatermarkSettings()
"""Глобальный экземпляр настроек WatermarkStore."""
