"""Настройки DLQ cleanup job (FIX-H1-DLQ-CLEANUP).

Периодический cleanup удаляет старые записи из ClickHouse ``dlq_events``
таблицы согласно retention-policy (:mod:`core.messaging.dlq_policy`).
Без этого job'а таблица растёт без ограничений.

Job (:class:`DLQCleanupJob`) существует, но ранее не планировался —
этот модуль + ``infrastructure.messaging.dlq.cleanup_lifecycle`` wire'ят
его в background asyncio-задачу через :class:`TaskRegistry`.

YAML-секция: ``dlq:`` в ``config_profiles/base.yml`` (опциональна —
все поля имеют default, поэтому отсутствие секции не валит загрузку).
ENV-prefix: ``DLQ_`` (например ``DLQ_INTERVAL_HOURS=12``).
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("DLQCleanupSettings", "dlq_cleanup_settings")


class DLQCleanupSettings(BaseSettingsWithLoader):
    """Конфигурация periodic DLQ retention cleanup.

    Поля:

    * ``enabled`` — feature-flag (default ON). При ``False`` lifecycle
      hook ``start_dlq_cleanup`` — no-op.
    * ``interval_hours`` — период запуска cleanup-job. Default 24h
      (ежедневно). Меньшие значения — чаще cleanup, но больше нагрузка
      на ClickHouse.
    * ``table_name`` — имя DLQ-таблицы в ClickHouse (default ``dlq_events``).
    """

    yaml_group: ClassVar[str] = "dlq"
    model_config = SettingsConfigDict(env_prefix="DLQ_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Feature-flag для periodic DLQ cleanup. При ``False`` "
            "lifecycle hook ``start_dlq_cleanup`` — no-op (таблица "
            "dlq_events растёт без ограничений)."
        ),
    )
    interval_hours: float = Field(
        default=24.0,
        ge=0.1,
        le=720.0,
        description=(
            "Период запуска cleanup-job в часах. Default 24h (ежедневно). "
            "Cleanup удаляет записи старше retention_days per dlq_class."
        ),
    )
    table_name: str = Field(
        default="dlq_events",
        description="Имя DLQ-таблицы в ClickHouse (default ``dlq_events``).",
    )


dlq_cleanup_settings = DLQCleanupSettings()
"""Глобальный экземпляр настроек DLQ cleanup job."""
