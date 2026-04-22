"""Единая модель pool-параметров для всех infrastructure-клиентов.

`PoolingProfile` нормализует параметры, которые раньше были разбросаны по
разным Settings-секциям с разными именами (pool_size / max_connections /
maxPoolSize / ...). Все клиенты, наследующие `InfrastructureClient` ABC
(см. ``src/infrastructure/clients/base_connector.py``), принимают
`PoolingProfile` как единственный источник правды для пулинга.

Коммерческий референс — MuleSoft `<pooling-profile>` element, Apache Commons
Pool `GenericObjectPoolConfig`.

См. ADR-022 и план IL1 в ``/root/.claude/plans/tidy-jingling-map.md``.
"""

from __future__ import annotations

from typing import ClassVar, Final

from pydantic import BaseModel, Field, model_validator


# Разумные defaults, применяются если конкретная Settings-секция не указала
# свой профиль. Подобраны консервативно под средний нагрузочный профиль
# (не high-load, но и не demo).
_DEFAULT_MIN_SIZE: Final = 2
_DEFAULT_MAX_SIZE: Final = 20
_DEFAULT_ACQUIRE_TIMEOUT_S: Final = 5.0
_DEFAULT_IDLE_TIMEOUT_S: Final = 300.0
_DEFAULT_MAX_LIFETIME_S: Final = 3600.0
_DEFAULT_EVICTION_CHECK_INTERVAL_S: Final = 60.0
_DEFAULT_CIRCUIT_THRESHOLD: Final = 5
_DEFAULT_CIRCUIT_RECOVERY_S: Final = 30.0


class PoolingProfile(BaseModel):
    """Унифицированный профиль пула для любого infra-клиента.

    Конкретный клиент применяет только релевантные поля:
      * Postgres/SQLAlchemy — min_size/max_size/max_lifetime_s/pre_ping.
      * Redis — max_size (maxconn), acquire_timeout_s (socket_timeout).
      * Kafka — circuit_threshold/circuit_recovery_s (producer CB).
      * HTTP (httpx) — max_size (max_connections), idle_timeout_s
        (keepalive_expiry).
    """

    model_config = {"frozen": False, "extra": "forbid"}

    # Минимальное число активных соединений в пуле (warm-pool).
    min_size: int = Field(
        default=_DEFAULT_MIN_SIZE,
        ge=0,
        le=1024,
        description="Минимальное число соединений, которые держатся 'тёплыми'.",
    )

    # Максимум параллельных соединений (hard cap).
    max_size: int = Field(
        default=_DEFAULT_MAX_SIZE,
        ge=1,
        le=4096,
        description="Максимум параллельных соединений (hard cap).",
    )

    # Сколько секунд ждать свободного соединения при acquire.
    acquire_timeout_s: float = Field(
        default=_DEFAULT_ACQUIRE_TIMEOUT_S,
        ge=0.1,
        le=600.0,
        description="Timeout на получение соединения из пула.",
    )

    # Через сколько секунд неактивное соединение закрывается.
    idle_timeout_s: float = Field(
        default=_DEFAULT_IDLE_TIMEOUT_S,
        ge=1.0,
        le=86400.0,
        description="После какого времени idle-соединение закрывается.",
    )

    # Максимальное время жизни соединения (эвакуация старых).
    max_lifetime_s: float = Field(
        default=_DEFAULT_MAX_LIFETIME_S,
        ge=60.0,
        le=86400.0,
        description="Максимальное время жизни соединения (защита от long-lived leaks).",
    )

    # Частота прохода evictor-а (закрытие протухших).
    eviction_check_interval_s: float = Field(
        default=_DEFAULT_EVICTION_CHECK_INTERVAL_S,
        ge=5.0,
        le=3600.0,
        description="Частота evictor-прохода.",
    )

    # Проверять соединение перед выдачей из пула (стоит I/O).
    pre_ping: bool = Field(
        default=True,
        description="Выполнять PING/SELECT 1 перед выдачей соединения.",
    )

    # Количество подряд идущих failures для перехода CB в OPEN.
    circuit_threshold: int = Field(
        default=_DEFAULT_CIRCUIT_THRESHOLD,
        ge=1,
        le=1000,
        description="Consecutive failures → circuit OPEN.",
    )

    # Сколько ждать в OPEN до перехода HALF_OPEN.
    circuit_recovery_s: float = Field(
        default=_DEFAULT_CIRCUIT_RECOVERY_S,
        ge=1.0,
        le=3600.0,
        description="Время удержания OPEN до пробы HALF_OPEN.",
    )

    # Перечень «стандартных» профилей, которые можно использовать по имени
    # из YAML-конфига. Конкретная Settings-секция может выбрать один из них
    # вместо явного набора полей. См. `PoolingProfile.named`.
    _NAMED_PROFILES: ClassVar[dict[str, dict[str, float | int | bool]]] = {
        "conservative": {
            "min_size": 2,
            "max_size": 10,
            "acquire_timeout_s": 5.0,
            "circuit_threshold": 3,
        },
        "default": {
            "min_size": _DEFAULT_MIN_SIZE,
            "max_size": _DEFAULT_MAX_SIZE,
        },
        "high_throughput": {
            "min_size": 10,
            "max_size": 100,
            "acquire_timeout_s": 2.0,
            "idle_timeout_s": 60.0,
            "circuit_threshold": 10,
        },
        "low_latency": {
            "min_size": 20,
            "max_size": 50,
            "acquire_timeout_s": 0.5,
            "pre_ping": False,
            "circuit_threshold": 2,
            "circuit_recovery_s": 10.0,
        },
    }

    @model_validator(mode="after")
    def _validate_sizes(self) -> "PoolingProfile":
        if self.min_size > self.max_size:
            raise ValueError(
                f"PoolingProfile: min_size ({self.min_size}) > max_size ({self.max_size})"
            )
        if self.max_lifetime_s < self.idle_timeout_s:
            raise ValueError(
                "PoolingProfile: max_lifetime_s должен быть ≥ idle_timeout_s"
            )
        return self

    @classmethod
    def named(cls, profile_name: str) -> "PoolingProfile":
        """Вернуть один из стандартных профилей по имени.

        Поддерживаемые имена: ``conservative`` | ``default`` |
        ``high_throughput`` | ``low_latency``.
        """
        preset = cls._NAMED_PROFILES.get(profile_name)
        if preset is None:
            available = ", ".join(sorted(cls._NAMED_PROFILES))
            raise KeyError(
                f"Unknown pooling profile '{profile_name}'. Available: {available}"
            )
        return cls.model_validate(preset)

    def merged_with(self, override: "PoolingProfile | dict[str, object]") -> "PoolingProfile":
        """Создать новый профиль, переопределяя только явно заданные поля."""
        if isinstance(override, PoolingProfile):
            override_dict = override.model_dump(exclude_unset=True)
        else:
            override_dict = dict(override)
        base = self.model_dump()
        base.update(override_dict)
        return PoolingProfile.model_validate(base)


#: Глобальный default-профиль. Клиенты, которые не указали свой pooling,
#: получают именно этот (в lifecycle.register_all_clients).
DEFAULT_POOLING_PROFILE: Final = PoolingProfile()


__all__ = ("PoolingProfile", "DEFAULT_POOLING_PROFILE")
