"""Настройки PG → SQLite snapshot job (Wave 26.8, ADR-0413).

Snapshot job периодически реплицирует критичные read-only таблицы из
PostgreSQL в локальный SQLite-файл (``var/db/snapshot.sqlite``). При
OPEN-breaker'е компонента ``db_main`` ``ResilienceCoordinator``
переключается на этот snapshot — см. ``database_chain.py::_sqlite_ro_query``.

Без этого job'а fallback читает либо stale-данные, либо вообще пустой
файл (создаваемый ``snapshot_path.touch()``), что нарушает контракт
fallback-цепочки (ADR-036) и поведение ``HealthAggregator`` в
degraded-режиме.

Межtenant-снапшот: режимы (ADR-0413)
------------------------------------
ADR-0409 зафиксировал контракт «снапшот в пределах одного ``tenant_id``;
без скоупа — fail-closed»: реестра tenant'ов в БД нет, а ``SELECT DISTINCT
tenant_id`` под RLS видит только текущего tenant'а. ADR-0413 добавляет
явную настройку режима:

* ``single-tenant`` (по умолчанию) — снимок одного tenant'а: скоуп из
  явного аргумента → tenant-контекста процесса; без скоупа — fail-closed.
* ``per-tenant`` — **безопасная** альтернатива ``BYPASSRLS``: явный
  список ``tenants`` перебирается с per-tenant ``SET app.tenant_id``.
  Пустой список — fail-closed (снимок не пишется).
* ``service-role`` — служебный DSN (``service_dsn``) пользователя с
  ``BYPASSRLS``; обходит RLS **только** для чтения. DSN не задан —
  fail-closed. Риски и процедура — ``docs/ops/snapshot-bypassrls-role.md``.

YAML-секция: ``snapshot:`` в ``config_profiles/base.yml``.
ENV-prefix: ``SNAPSHOT_``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import Field, SecretStr, field_serializer
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.base import mask_url_password
from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("SnapshotSettings", "snapshot_settings")


#: Режимы межtenant-снапшота (ADR-0413).
SNAPSHOT_MODE_SINGLE_TENANT = "single-tenant"
SNAPSHOT_MODE_PER_TENANT = "per-tenant"
SNAPSHOT_MODE_SERVICE_ROLE = "service-role"

#: Тип поля ``snapshot.mode`` — Literal из тех же значений, что и константы
#: выше (единство источников истины проверяется тестом
#: ``tests/unit/infrastructure/resilience/test_snapshot_job_modes.py``).
SnapshotMode = Literal["single-tenant", "per-tenant", "service-role"]


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
      startup hook (initial sync). Безопасен даже если файл существует.
    * ``mode`` — режим межtenant-снапшота (ADR-0413): ``single-tenant``
      (по умолчанию) / ``per-tenant`` / ``service-role``.
    * ``tenants`` — явный список tenant_id для режима ``per-tenant``.
      Пустой список — fail-closed (снимок не пишется).
    * ``service_dsn`` — DSN служебной роли с ``BYPASSRLS`` для режима
      ``service-role``. Содержит пароль — ``SecretStr`` (ADR-0378).
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
    mode: SnapshotMode = Field(
        default=SNAPSHOT_MODE_SINGLE_TENANT,
        description=(
            "Режим межtenant-снапшота (ADR-0413). 'single-tenant' — снимок "
            "одного tenant'а (по умолчанию, текущее поведение). "
            "'per-tenant' — перебор ЯВНОГО списка 'tenants' с per-tenant "
            "SET app.tenant_id (без BYPASSRLS). 'service-role' — чтение "
            "служебной ролью с BYPASSRLS по DSN из 'service_dsn'."
        ),
    )
    tenants: list[str] = Field(
        default_factory=list,
        description=(
            "Явный список tenant_id для режима 'per-tenant' (ADR-0413). "
            "Пустой список в режиме 'per-tenant' — fail-closed: снимок "
            "не пишется (иначе получился бы тихий 0-строчный снимок)."
        ),
    )
    service_dsn: SecretStr | None = Field(
        default=None,
        description=(
            "DSN служебной роли с BYPASSRLS для режима 'service-role' "
            "(ADR-0413). Роль обходит RLS — применять только для "
            "read-only служебного снимка, не для приложения "
            "(см. docs/ops/snapshot-bypassrls-role.md)."
        ),
    )

    @field_serializer("service_dsn")
    def _serialize_service_dsn(self, value: SecretStr | None) -> str | None:
        """Маскирует пароль в DSN служебной роли (ADR-0378).

        Args:
            value: Значение поля (DSN с паролем).

        Returns:
            DSN с замаскированным паролем либо ``None``.

        """
        if value is None:
            return None
        return mask_url_password(value.get_secret_value())


snapshot_settings = SnapshotSettings()
"""Глобальный экземпляр настроек snapshot job'а."""
