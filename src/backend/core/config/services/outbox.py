"""Настройки Outbox dispatcher (V15 K2 W2, L-scope).

Pydantic-Settings контейнер для production polling/delivery/retry/DLQ
цикла :class:`OutboxDispatcher`. Default-OFF feature-flag: на dev_light
и в legacy-окружениях диспетчер не стартует, пока ``enabled=False``.

YAML-секция: ``outbox:`` в ``config_profiles/base.yml`` (опциональна —
все поля имеют default, поэтому отсутствие секции не валит загрузку).
ENV-prefix: ``OUTBOX_`` (например ``OUTBOX_ENABLED=true``).

Wave: ``[wave:s8/k2-w2-outbox-config]``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("OutboxSettings", "outbox_settings")


class OutboxSettings(BaseSettingsWithLoader):
    """Конфигурация production Outbox dispatcher (L-scope).

    Поля:

    * ``enabled`` — feature-flag (default-OFF). При ``False`` lifecycle
      hook ``start_outbox_dispatcher`` — no-op; ``OutboxDispatcher.start``
      также ничего не делает.
    * ``poll_interval_seconds`` — пауза между итерациями polling в сек.
    * ``batch_size`` — максимум событий за одну итерацию.
    * ``max_retries`` — максимум попыток доставки одного события до
      DLQ-handoff (включая первую попытку).
    * ``retry_backoff_seconds`` — начальная задержка retry; следующая —
      ``retry_backoff_seconds * 2^(attempt-1)`` (exponential).
    * ``shutdown_timeout_seconds`` — общий timeout graceful shutdown.
    """

    yaml_group: ClassVar[str] = "outbox"
    model_config = SettingsConfigDict(env_prefix="OUTBOX_", extra="forbid")

    enabled: bool = Field(
        default=False,
        description=(
            "Feature-flag для OutboxDispatcher (default-OFF). При ``False`` "
            "lifecycle hook ``start_outbox_dispatcher`` и сам ``start`` "
            "являются no-op. Активируйте только при готовом репозитории "
            "Outbox и DLQ-handler."
        ),
    )
    use_redis_dedupe: bool = Field(
        default=False,
        description=(
            "S64 W4: feature-flag для cross-instance dedup store. "
            "``False`` (default) → MemoryDedupeStore (in-process, "
            "TTLCache + asyncio.Lock — single-instance only). "
            "``True`` → RedisDedupeStore (atomic SET NX EX, "
            "multi-instance safe, требует живой Redis)."
        ),
    )
    poll_interval_seconds: float = Field(
        default=1.0,
        ge=0.05,
        le=300.0,
        description=(
            "Пауза между итерациями polling в секундах. Меньшие значения "
            "снижают задержку доставки, но повышают нагрузку на БД."
        ),
    )
    batch_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description=(
            "Максимальное число событий, забираемых из репозитория за одну "
            "итерацию ``_poll_and_dispatch``."
        ),
    )
    max_retries: int = Field(
        default=5,
        ge=1,
        le=100,
        description=(
            "Максимальное число попыток доставки одного события до "
            "перевода в DLQ (включая первую попытку)."
        ),
    )
    retry_backoff_seconds: float = Field(
        default=2.0,
        ge=0.01,
        le=600.0,
        description=(
            "Начальная задержка между попытками retry в секундах. "
            "Каждая следующая удваивается (exponential backoff)."
        ),
    )
    shutdown_timeout_seconds: float = Field(
        default=10.0,
        ge=0.1,
        le=600.0,
        description=(
            "Общий timeout graceful shutdown: ждём дренажа текущей "
            "итерации, после — task.cancel()."
        ),
    )


outbox_settings = OutboxSettings()
"""Глобальный экземпляр настроек Outbox dispatcher."""
