"""Настройки PG → SQLite snapshot job (Wave 26.8).

Snapshot job периодически реплицирует критичные read-only таблицы из
PostgreSQL в локальный SQLite-файл (``var/db/snapshot.sqlite``). При
OPEN-breaker'е компонента ``db_main`` ``ResilienceCoordinator``
переключается на этот snapshot — см. ``database_chain.py::_sqlite_ro_query``.

Без этого job'а fallback читает либо stale-данные, либо вообще пустой
файл (создаваемый ``snapshot_path.touch()``), что нарушает контракт
fallback-цепочки (ADR-036) и поведение ``HealthAggregator`` в
degraded-режиме.

YAML-секция: ``snapshot:`` в ``config_profiles/base.yml``.
ENV-prefix: ``SNAPSHOT_``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SnapshotSettings", "snapshot_settings")


class SnapshotSettings(BaseSettingsWithLoader):
    """Конфигурация PG → SQLite snapshot-задачи (Wave 26.8).

    Поля:

    * ``enabled`` — глобальный флаг. Для dev_light (где SQLite primary)
      snapshot не нужен; для prod/staging — обязателен.
    * ``interval_minutes`` — частота полного refresh'а (cron-like).
    * ``tables`` — упорядоченный список read-only critical таблиц,
      которые реплицируются. Порядок важен (FK / lookup-таблицы первыми).
    * ``fresh_threshold_seconds`` — после которого snapshot считается
      stale и fallback публикует degraded-confidence метрику.
    * ``target_path`` — путь к SQLite-файлу. Должен совпадать с тем, что
      ожидает ``database_chain._get_sqlite_engine``.
    * ``run_on_startup`` — запускать ``run_snapshot_now()`` в lifespan
      startup hook (initial sync). Безопасно даже если файл существует.
    """

    yaml_group: ClassVar[str] = "snapshot"
    model_config = SettingsConfigDict(env_prefix="SNAPSHOT_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Глобальный флаг snapshot-job'а. Отключать только если SQLite "
            "primary (dev_light) — иначе fallback db_main → sqlite_ro "
            "будет работать с пустым/stale файлом."
        ),
    )
    interval_minutes: int = Field(
        default=10,
        ge=1,
        le=1440,
        description=(
            "Период полного refresh'а snapshot'а (cron-like). Рекомендуется "
            "10-30 минут: чаще — нагружает PG, реже — растёт лаг fallback'а."
        ),
    )
    tables: list[str] = Field(
        default_factory=list,
        description=(
            "Упорядоченный список read-only critical таблиц для репликации. "
            "Порядок важен: lookup / FK-таблицы первыми (orderkinds → orders)."
        ),
    )
    fresh_threshold_seconds: int = Field(
        default=1800,
        ge=60,
        description=(
            "Порог свежести snapshot'а. При превышении ``is_snapshot_fresh`` "
            "возвращает False, метрика ``snapshot_age_seconds`` показывает "
            "превышение, и fallback логирует degraded-confidence."
        ),
    )
    target_path: str = Field(
        default="var/db/snapshot.sqlite",
        description=(
            "Project-relative путь к SQLite-snapshot файлу. Совпадает с "
            "путём в ``database_chain._get_sqlite_engine``."
        ),
    )
    run_on_startup: bool = Field(
        default=True,
        description=(
            "Запускать ``run_snapshot_now()`` в lifespan startup hook. "
            "Initial sync — необходим для холодного старта (snapshot-файл "
            "ещё не создан) и безопасен (idempotent)."
        ),
    )


snapshot_settings = SnapshotSettings()
"""Глобальный экземпляр настроек snapshot job'а."""
