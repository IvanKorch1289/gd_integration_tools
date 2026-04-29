from typing import ClassVar, Literal

from pydantic import Field, computed_field, field_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader


class RedisSettings(BaseSettingsWithLoader):
    """Настройки подключения к Redis."""

    yaml_group: ClassVar[str] = "redis"
    model_config = SettingsConfigDict(env_prefix="REDIS_", extra="forbid")

    enabled: bool = Field(
        default=True,
        description=(
            "Включить интеграцию с Redis. Для dev_light устанавливается "
            "``false`` через ``config_profiles/dev_light.yml`` — заменяется "
            "in-memory backend (cachetools)."
        ),
    )

    # Основные параметры подключения
    host: str = Field(
        ..., description="Хост или IP-адрес сервера Redis", example="redis.example.com"
    )
    port: int = Field(
        ..., ge=1, le=65535, description="Порт сервера Redis", example=6379
    )
    password: str | None = Field(
        ...,
        description="Пароль для аутентификации в Redis",
        example="securepassword123",
    )
    encoding: str = Field(
        ..., description="Кодировка для сериализации данных", example="utf-8"
    )

    # Параметры баз данных
    db_cache: int = Field(
        ..., ge=0, description="Номер базы данных для кэширования", example=0
    )
    db_queue: int = Field(
        ..., ge=0, description="Номер базы данных для управления очередями", example=1
    )
    db_limits: int = Field(
        ..., ge=0, description="Номер базы данных для ограничений скорости", example=2
    )
    db_tasks: int = Field(
        ..., ge=0, description="Номер базы данных для Celery", example=3
    )

    # Параметры производительности
    cache_expire_seconds: int = Field(
        ..., ge=60, description="Время жизни кэша по умолчанию в секундах", example=300
    )
    max_connections: int = Field(
        ..., ge=1, description="Максимальное количество соединений в пуле", example=20
    )
    socket_timeout: int | None = Field(
        ..., ge=1, description="Таймаут операций с сокетом в секундах", example=10
    )
    socket_connect_timeout: int | None = Field(
        ..., ge=1, description="Таймаут установления соединения в секундах", example=5
    )
    retry_on_timeout: bool | None = Field(
        ...,
        description="Включить автоматический повтор при таймауте соединения",
        example=False,
    )
    socket_keepalive: bool | None = Field(
        ..., description="Включить TCP keepalive для соединений", example=True
    )

    # Параметры безопасности
    use_ssl: bool = Field(
        ..., description="Включить SSL/TLS для безопасных соединений", example=False
    )
    ca_bundle: str | None = Field(
        ...,
        description="Путь к пакету CA-сертификатов для проверки SSL",
        example="/path/to/ca_bundle.crt",
    )

    # Параметры потоков
    main_stream: str | None = Field(
        ..., description="Имя основного потока Redis", example="example-stream"
    )
    dlq_stream: str | None = Field(
        ..., description="Имя потока DLQ Redis", example="dlq-example-stream"
    )
    max_stream_len: int = Field(
        ..., description="Максимальный размер потока Redis", example=100000
    )
    approximate_trimming_stream: bool = Field(
        ...,
        description="Включить приблизительную обрезку для потоков Redis",
        example=True,
    )
    retention_hours_stream: int = Field(
        ..., description="Время хранения потоков Redis в часах", example=24
    )
    max_retries: int = Field(
        ...,
        description="Максимальное количество попыток чтения сообщения в потоке",
        example=1,
    )
    ttl_hours: int = Field(..., description="Время жизни сообщений в потоке", example=1)
    health_check_interval: int = Field(
        ..., description="Интервал проверки работоспособности", example=600
    )
    streams: list[dict[str, str]] = Field(
        ...,
        min_items=1,
        description="Список потоков Redis",
        example=[
            {"name": "stream1", "value": "creating-stream"},
            {"name": "stream2", "value": "updating-stream"},
        ],
    )

    @computed_field(description="Создает URL подключения к Redis")
    def redis_url(self) -> str:
        """Создает URL подключения к Redis."""
        protocol = "rediss" if self.use_ssl else "redis"
        auth = f":{self.password}@" if self.password else ""
        return f"{protocol}://{auth}{self.host}:{self.port}"

    @field_validator("port", "db_cache", "db_queue", "db_limits", "db_tasks")
    @classmethod
    def validate_redis_numbers(cls, v):
        if isinstance(v, int) and v < 0:
            raise ValueError("Значение должно быть неотрицательным целым числом")
        return v

    def get_stream_name(self, stream_key: str) -> str:
        stream = next(
            (
                stream
                for stream in self.streams
                if stream.get("name", None) == stream_key
            ),
            None,
        )

        if not stream:
            raise ValueError(f"Не настроен поток для ключа: {stream_key}")

        return stream["value"]


redis_settings = RedisSettings()


class CacheSettings(BaseSettingsWithLoader):
    """Настройки бэкенда кэширования (Wave 2.2).

    KeyDB — drop-in замена Redis (тот же RESP-протокол, многопоточная
    реализация). Переключение между backend'ами без изменения кода:
    ``CACHE_BACKEND=keydb``.

    Поля backend / l1_* / max_connections имеют дефолты; YAML-группа
    ``cache`` опциональна.
    """

    yaml_group: ClassVar[str] = "cache"
    model_config = SettingsConfigDict(env_prefix="CACHE_", extra="forbid")

    backend: Literal["redis", "keydb", "memcached", "memory"] = Field(
        default="redis",
        description="Бэкенд кэша. KeyDB — drop-in замена Redis.",
        examples=["redis", "keydb", "memory"],
    )
    l1_enabled: bool = Field(
        default=True,
        description="Использовать ли in-process L1-кэш поверх удалённого backend'а.",
    )
    l1_maxsize: int = Field(
        default=1000,
        ge=1,
        le=100_000,
        description="Размер L1 cachetools.TTLCache по умолчанию.",
    )
    keydb_active_replica: bool = Field(
        default=False,
        description=(
            "Включить multi-master режим KeyDB (active-active). "
            "Требует соответствующего deployment."
        ),
    )


cache_settings = CacheSettings()
"""Глобальный экземпляр настроек cache backend factory."""
"""Глобальные настройки Redis"""
