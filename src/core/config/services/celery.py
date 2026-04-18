from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader


class CelerySettings(BaseSettingsWithLoader):
    """Настройки для управления очередями задач и воркерами Celery."""

    yaml_group: ClassVar[str] = "celery"
    model_config = SettingsConfigDict(env_prefix="CELERY_", extra="forbid")

    # Основные параметры
    redis_db: int = Field(
        ..., ge=0, description="Номер базы данных Redis для брокера Celery", example=0
    )
    task_default_queue: str = Field(
        "default",
        description="Имя очереди по умолчанию для маршрутизации задач",
        example="default",
    )
    task_serializer: Literal["json", "pickle", "yaml", "msgpack"] = Field(
        ..., description="Формат сериализации задач", example="json"
    )

    # Параметры задач
    task_time_limit: int = Field(
        ...,
        ge=60,
        description="Максимальное время выполнения задачи (в секундах) перед завершением",
        example=300,
    )
    task_soft_time_limit: int = Field(
        ...,
        ge=60,
        description="Время (в секундах) после которого задача получает SIGTERM для graceful shutdown",
        example=240,
    )
    task_max_retries: int = Field(
        ...,
        ge=0,
        description="Максимальное количество автоматических попыток для неудачных задач",
        example=3,
    )
    task_min_retries: int = Field(
        ...,
        ge=0,
        description="Минимальное количество автоматических попыток для неудачных задач",
        example=1,
    )
    task_default_retry_delay: int = Field(
        ...,
        ge=0,
        description="Задержка по умолчанию (в секундах) перед повторной попыткой выполнения задачи",
        example=60,
    )
    task_retry_backoff: int = Field(
        ...,
        ge=0,
        description="Базовое время отката (в секундах) для расчета задержки повторной попытки",
        example=10,
    )
    task_retry_jitter: bool = Field(
        ...,
        description="Включить случайный джиттер для предотвращения лавины повторных попыток",
        example=True,
    )
    countdown_time: int = Field(
        ...,
        ge=0,
        description="Начальная задержка (в секундах) перед выполнением задачи после отправки",
        example=0,
    )

    # Параметры воркеров
    worker_concurrency: int = Field(
        ...,
        ge=1,
        description="Количество параллельных процессов/потоков воркера",
        example=4,
    )
    worker_prefetch_multiplier: int = Field(
        ...,
        ge=1,
        description="Множитель для количества предварительной выборки воркера (concurrency * multiplier)",
        example=4,
    )
    worker_max_tasks_per_child: int = Field(
        ...,
        ge=1,
        description="Максимальное количество задач, выполняемых воркером перед перезапуском",
        example=100,
    )
    worker_disable_rate_limits: bool = Field(
        ..., description="Отключить ограничение скорости для воркеров", example=False
    )
    worker_send_events: bool = Field(
        ...,
        description="Включить отправку событий, связанных с задачами, для мониторинга",
        example=True,
    )

    # Параметры мониторинга
    flower_url: str = Field(
        ...,
        description="URL-адрес для мониторинга через Flower",
        example="http://flower.example.com:5555",
    )
    flower_basic_auth: tuple[str, str] | None = Field(
        ...,
        description="Учетные данные для базовой аутентификации в Flower (логин, пароль)",
        example=("admin", "secret"),
    )

    # Параметры брокера
    broker_pool_limit: int = Field(
        ...,
        ge=1,
        description="Максимальное количество соединений в пуле брокера",
        example=10,
    )
    result_extended: bool = Field(
        ...,
        description="Включить расширенное хранение метаданных результатов",
        example=True,
    )
    task_track_started: bool = Field(
        ...,
        description="Включить отслеживание состояния STARTED для задач",
        example=True,
    )

    @field_validator("flower_basic_auth")
    @classmethod
    def validate_auth(cls, v):
        if v and (len(v) != 2 or not all(isinstance(i, str) for i in v)):
            raise ValueError(
                "Аутентификация должна быть кортежем из двух строк (логин, пароль)"
            )
        return v


celery_settings = CelerySettings()
"""Глобальные настройки Celery"""
