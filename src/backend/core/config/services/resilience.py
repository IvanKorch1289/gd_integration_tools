"""Настройки устойчивой инфраструктуры (W26).

Содержит per-service breaker-профили и fallback-политики для 11
компонентов, перечисленных в плане Wave 26: db_main / redis / minio /
vault / clickhouse / mongodb / elasticsearch / kafka / clamav / smtp /
express.

YAML-секция ``resilience:`` в ``config_profiles/base.yml`` задаёт дефолты,
overlay-профили (``dev_light.yml`` и др.) могут переопределить ``mode``
fallback'ов или disable отдельные breaker-ы.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader
from src.backend.core.config.constants import consts

__all__ = (
    "BreakerProfile",
    "FallbackPolicy",
    "ResilienceSettings",
    "resilience_settings",
)


FallbackMode = Literal["auto", "forced", "off"]


class BreakerProfile(BaseModel):
    """Параметры circuit breaker'а для конкретного компонента.

    ``threshold`` — количество подряд идущих отказов до перехода в open.
    ``ttl`` — секунды в open до перехода в half-open.
    ``exclude`` — qualified-имена исключений, не учитывающихся как failure
    (например, бизнес-ошибки 4xx, не свидетельствующие о проблемах с
    инфраструктурой).
    """

    model_config = ConfigDict(extra="forbid")

    threshold: int = Field(
        default=consts.DEFAULT_CB_FAILURE_THRESHOLD,
        ge=1,
        le=100,
        description="Порог отказов до перехода breaker'а в open.",
    )
    ttl: float = Field(
        default=consts.DEFAULT_CB_RECOVERY_SECONDS,
        gt=0,
        description="Секунды в open до перехода в half-open.",
    )
    exclude: list[str] = Field(
        default_factory=list,
        description=(
            "Qualified-имена исключений, не учитывающихся как failure. "
            "Например, ['httpx.HTTPStatusError'] для 4xx ошибок."
        ),
    )


class FallbackPolicy(BaseModel):
    """Описание fallback-цепочки для компонента.

    ``chain`` — упорядоченный список идентификаторов backend'ов, к которым
    coordinator переключается при OPEN-состоянии primary breaker'а.
    Идентификаторы соответствуют именам, под которыми backend'ы
    зарегистрированы в ``ResilienceCoordinator`` (см.
    ``infrastructure/resilience/registration.py``).

    ``mode``:
        * ``auto`` — переключение автоматическое по состоянию breaker'а;
        * ``forced`` — fallback активен всегда (для dev_light без primary);
        * ``off`` — fallback выключен, отказ primary распространяется наружу.
    """

    model_config = ConfigDict(extra="forbid")

    chain: list[str] = Field(
        default_factory=list,
        description="Упорядоченный список backend-идентификаторов fallback'а.",
    )
    mode: FallbackMode = Field(
        default="auto", description="Режим срабатывания: auto / forced / off."
    )


class ResilienceSettings(BaseSettingsWithLoader):
    """Настройки W26: per-service breaker-профили + fallback-политики.

    YAML-секция ``resilience:`` ожидает структуру:

    .. code-block:: yaml

        resilience:
          breakers:
            db_main: {threshold: 5, ttl: 30}
            redis: {threshold: 5, ttl: 15}
          fallbacks:
            db_main: {chain: ["sqlite_ro"], mode: auto}
            redis: {chain: ["memcached", "memory"], mode: auto}

    Поля имеют разумные дефолты — отсутствие YAML-секции не ломает запуск.
    """

    yaml_group: ClassVar[str] = "resilience"
    model_config = SettingsConfigDict(env_prefix="RESILIENCE_", extra="forbid")

    breakers: dict[str, BreakerProfile] = Field(
        default_factory=dict,
        description=(
            "Per-component breaker-профили. Ключ — имя компонента "
            "(db_main, redis, kafka и т.д.)."
        ),
    )
    fallbacks: dict[str, FallbackPolicy] = Field(
        default_factory=dict,
        description=(
            "Per-component fallback-политики. Ключ — имя компонента, "
            "значение — упорядоченная chain backend'ов и mode."
        ),
    )
    fallback_mode_override: FallbackMode | None = Field(
        default=None,
        description=(
            "Глобальный override mode для всех fallback-политик. "
            "Полезно для CI/chaos-тестов: RESILIENCE_FALLBACK_MODE_OVERRIDE=forced."
        ),
    )


resilience_settings = ResilienceSettings()
"""Глобальный экземпляр настроек resilience."""
