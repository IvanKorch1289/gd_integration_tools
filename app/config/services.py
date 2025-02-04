import re
from pathlib import Path
from typing import Any, ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.config.config_loader import BaseYAMLSettings


__all__ = (
    "FileStorageSettings",
    "fs_settings",
    "LogStorageSettings",
    "log_settings",
    "RedisSettings",
    "CelerySettings",
    "celery_settings",
    "MailSettings",
    "mail_settings",
    "QueueSettings",
    "queue_settings",
)


class FileStorageSettings(BaseYAMLSettings):
    """Settings for connecting to an S3-compatible object storage.

    Configuration groups:
    - Storage provider settings
    - Authentication
    - Connection parameters
    - SSL/TLS settings
    - Retry policies
    - Key management
    """

    yaml_group: ClassVar[str] = "fs"
    model_config = SettingsConfigDict(env_prefix="FS_", extra="forbid")

    # Storage provider settings
    provider: Literal["minio", "aws", "other"] = Field(
        ...,
        description="Type of storage provider",
        example="minio",
    )
    bucket: str = Field(
        default="my-bucket",
        env="FS_BUCKET",
        description="Default bucket name",
        example="my-bucket",
    )

    # Authentication
    access_key: str = Field(
        ...,
        description="Access key for the storage",
        example="AKIAIOSFODNN7EXAMPLE",
    )
    secret_key: str = Field(
        ...,
        description="Secret access key for the storage",
        example="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    # Connection parameters
    endpoint: str = Field(
        ...,
        description="API endpoint URL of the storage",
        example="https://s3.example.com",
    )
    interface_endpoint: str = Field(
        ...,
        description="Web interface URL of the storage",
        example="https://console.s3.example.com",
    )
    use_ssl: bool = Field(
        ...,
        description="Use HTTPS for connections",
        example=True,
    )

    # SSL/TLS settings
    verify: bool = Field(
        ...,
        description="Verify SSL certificates",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        env="FS_CA_BUNDLE",
        description="Path to the CA certificate bundle for SSL",
        example="/path/to/ca-bundle.crt",
    )

    # Retry policies
    timeout: int = Field(
        ...,
        description="Timeout for operations (in seconds)",
        example=30,
    )
    retries: int = Field(
        ...,
        description="Number of retries for failed operations",
        example=3,
    )

    # Key management
    key_prefix: str = Field(
        ...,
        description="Prefix for object keys",
        example="my-prefix/",
    )

    @property
    def normalized_endpoint(self) -> str:
        """Returns the endpoint without the connection scheme (e.g., 'https://')."""
        return str(self.endpoint).split("://")[-1]


# Instantiate settings for immediate use
fs_settings = FileStorageSettings()


class LogStorageSettings(BaseYAMLSettings):
    """Settings for the logging and log storage system.

    Configuration groups:
    - Connection parameters
    - Security settings
    - Log format settings
    - Log validation
    """

    yaml_group: ClassVar[str] = "log"
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        extra="forbid",
    )

    # Connection parameters
    host: str = Field(
        ...,
        description="Log server host",
        example="logs.example.com",
    )
    port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="TCP port of the log server",
        example=514,
    )
    udp_port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="UDP port for sending logs",
        example=514,
    )
    conf_loggers: List[Dict] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Configuration for loggers",
        example=[{"name": "application", "facility": "application"}],
    )

    # Security settings
    use_tls: bool = Field(
        ...,
        description="Use TLS for secure connections",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        description="Path to the CA certificate bundle",
        example="/path/to/ca-bundle.crt",
    )

    # Log format settings
    level: str = Field(
        ...,
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Logging level of detail",
        example="INFO",
    )
    name_log_file: str = Field(
        ...,
        description="Path to the log file",
        example="app.log",
    )
    dir_log_name: str = Field(
        ...,
        description="Directory name for log files",
        example="/var/logs/myapp",
    )

    # Log validation
    required_fields: List[str] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Mandatory fields in log messages",
        example={"timestamp", "level", "message"},
    )


# Instantiate settings for immediate use
log_settings = LogStorageSettings()


class RedisSettings(BaseYAMLSettings):
    """Настройки для подключения к Redis.

    Attributes:
        redis_host (str): Хост Redis. По умолчанию 'localhost'.
        redis_port (int): Порт Redis. По умолчанию 6379.
        redis_db_cache (int): Номер базы данных для кэширования. По умолчанию 0.
        redis_db_queue (int): Номер базы данных для очередей. По умолчанию 1.
        redis_db_limits (int): Номер базы данных для лимитов. По умолчанию 2.
        redis_pass (Optional[str]): Пароль Redis. По умолчанию None.
        redis_encoding (str): Кодировка данных в Redis. По умолчанию 'utf-8'.
        redis_decode_responses (bool): Флаг декодирования ответов от Redis. По умолчанию True.
        redis_cache_expire_seconds (int): Время жизни кэша в секундах. По умолчанию 300.
        redis_connect_timeout (int): Таймаут подключения в секундах. По умолчанию 5.
        redis_timeout (int): Таймаут операций чтения/записи в секундах. По умолчанию 10.
        redis_pool_maxsize (int): Максимальное количество соединений в пуле. По умолчанию 20.
        redis_pool_minsize (int): Минимальное количество свободных соединений. По умолчанию 5.
        redis_use_ssl (bool): Использовать SSL-подключение. По умолчанию False.
        redis_ssl_ca_certs (Optional[str]): Путь к CA сертификату. По умолчанию None.
        redis_retries (int): Количество попыток повторного подключения. По умолчанию 3.
        redis_retry_delay (int): Задержка между попытками подключения в секундах. По умолчанию 1.

    Methods:
        redis_url: Возвращает URL для подключения к Redis.
    """

    yaml_group: ClassVar[str] = "redis"
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        extra="forbid",
    )

    host: str = Field(...)
    port: int = Field(...)
    db_cache: int = Field(...)
    db_queue: int = Field(...)
    db_limits: int = Field(...)
    db_celery: int = Field(...)
    username: Optional[str] = Field(...)
    password: Optional[str] = Field(...)
    encoding: str = Field(...)
    cache_expire_seconds: int = Field(...)
    max_connections: int = Field(...)
    use_ssl: bool = Field(...)
    ca_bundle: Optional[str] = Field(...)
    socket_timeout: Optional[int] = Field(...)
    socket_connect_timeout: Optional[int] = Field(...)
    retry_on_timeout: Optional[bool] = Field(...)
    socket_keepalive: Optional[bool] = Field(...)

    @property
    def redis_url(self) -> str:
        """Сформировать URL для подключения к Redis."""
        protocol = "rediss" if self.use_ssl else "redis"
        password = f":{self.password}@" if self.password else None
        return f"{protocol}://{password}{self.host}:{self.port}"


redis_settings = RedisSettings()


class CelerySettings(BaseYAMLSettings):
    """Настройки для Celery (фоновые задачи и воркеры).

    Группы параметров:
    - Подключение к брокеру
    - Поведение задач
    - Конфигурация воркеров
    - Мониторинг и трекинг
    - Оптимизация производительности
    """

    yaml_group: ClassVar[str] = "celery"
    model_config = SettingsConfigDict(
        env_prefix="CELERY_",
        extra="forbid",
    )

    # Подключение к брокеру
    redis_db: int = Field(
        ...,
        description="Номер БД для брокера",
    )

    # Поведение задач
    task_default_queue: str = Field(
        ...,
        description="Очередь по умолчанию для задач",
    )
    task_serializer: Literal["json", "pickle", "yaml", "msgpack"] = Field(
        ...,
        description="Сериализатор для задач",
    )
    task_time_limit: int = Field(
        ...,
        ge=60,
        description="Максимальное время выполнения задачи (секунды)",
    )
    task_soft_time_limit: int = Field(
        ...,
        description="Мягкий таймаут перед отправкой SIGTERM",
    )
    task_max_retries: int = Field(
        ...,
        ge=3,
        description="Максимальное количество повторных попыток",
    )
    task_min_retries: int = Field(
        ...,
        ge=0,
        description="Миниальное количество повторных попыток",
    )
    task_default_retry_delay: int = Field(
        ...,
        ge=0,
        description="Задержка перед повторной попыткой",
    )
    task_retry_backoff: int = Field(
        ...,
        description="Базовая задержка перед повтором (секунды)",
    )
    task_retry_jitter: bool = Field(
        ...,
        description="Добавлять случайный джиттер к задержке",
    )
    countdown_time: int = Field(
        ...,
        description="Задержка перед запуском задачи  (секунды)",
    )

    # Конфигурация воркеров
    worker_concurrency: int = Field(
        ...,
        ge=1,
        description="Количество параллельных процессов воркера",
    )
    worker_prefetch_multiplier: int = Field(
        ...,
        description="Множитель предварительной выборки задач",
    )
    worker_max_tasks_per_child: int = Field(
        ...,
        description="Максимум задач до перезапуска процесса",
    )
    worker_disable_rate_limits: bool = Field(
        ...,
        description="Отключить лимиты скорости выполнения",
    )

    # Мониторинг
    flower_url: str = Field(
        ...,
        description="Адрес веб-интерфейса Flower",
    )
    flower_basic_auth: Tuple[str, str] | None = Field(
        ...,
        description="Логин/пароль для Flower в формате (user, password)",
    )
    task_track_started: bool = Field(
        ...,
        description="Отслеживать статус STARTED для задач",
    )

    # Оптимизация
    broker_pool_limit: int = Field(
        ...,
        description="Максимум соединений с брокером",
    )
    result_extended: bool = Field(
        ...,
        description="Хранить расширенные метаданные результатов",
    )
    worker_send_events: bool = Field(
        ...,
        description="Отправлять события для мониторинга",
    )

    @field_validator("flower_basic_auth")
    @classmethod
    def validate_auth(cls, v):
        if v and len(v) != 2:
            raise ValueError("Auth must be tuple of (username, password)")
        return v


celery_settings = CelerySettings()


class MailSettings(BaseYAMLSettings):
    """Настройки электронной почты.

    Группы параметров:
    - Параметры сервера
    - Аутентификация
    - Настройки TLS
    - Параметры писем
    """

    yaml_group: ClassVar[str] = "mail"
    model_config = SettingsConfigDict(
        env_prefix="MAIL_",
        extra="forbid",
    )

    # Параметры сервера
    host: str = Field(
        ...,
        description="SMTP сервер для отправки почты",
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Порт SMTP сервера",
    )
    connection_pool_size: int = Field(
        ...,
        ge=1,
        le=10,
        description="Размер пула подключений к SMTP серверу",
    )

    # Аутентификация
    username: str = Field(
        ...,
        description="Логин для SMTP аутентификации",
    )
    password: str = Field(
        ...,
        description="Пароль для SMTP аутентификации",
    )

    # Настройки TLS
    use_tls: bool = Field(
        ...,
        description="Использовать STARTTLS для шифрования",
    )
    validate_certs: bool = Field(
        ...,
        description="Проверять SSL сертификаты сервера",
    )
    ca_bundle: Optional[str] = Field(..., description="Путь к CA сертификату")

    # Параметры писем
    sender: str = Field(
        ...,
        description="Email отправителя по умолчанию",
    )
    template_folder: str | None = Field(
        ...,
        description="Email отправителя по умолчанию",
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v):
        if v == 465 and not cls.use_tls:
            raise ValueError("Порт 465 требует SSL/TLS")
        return v

    @field_validator("use_tls", "validate_certs", mode="before")
    @classmethod
    def parse_bool(cls, v):
        if isinstance(v, str):
            return v.lower() == "true"
        return v


mail_settings = MailSettings()


class QueueSettings(BaseYAMLSettings):
    """Настройки брокера сообщений.

    Группы параметров:
    - Основные параметры
    - Настройки потребителя (Consumer)
    - Настройки производителя (Producer)
    - Безопасность
    - Оптимизация производительности
    - Таймауты и повторы
    """

    yaml_group: ClassVar[str] = "queue"
    model_config = SettingsConfigDict(
        env_prefix="QUEUE_",
        extra="forbid",
    )

    # Основные параметры
    type: Literal["kafka", "rabbitmq"] = Field(
        ..., description="Тип брокера сообщений"
    )
    bootstrap_servers: List[str] = Field(
        ...,
        description="Список серверов брокера",
    )

    # Настройки потребителя
    consumer_group: str = Field(
        ...,
        description="Группа потребителей (Kafka)",
    )
    auto_offset_reset: Literal["earliest", "latest"] = Field(
        ...,
        description="Поведение при отсутствии оффсета",
    )
    max_poll_records: int = Field(
        ...,
        ge=1,
        le=10000,
        description="Максимальное количество записей за опрос",
    )

    # Настройки производителя
    producer_acks: Literal["all", "0", "1"] = Field(
        ...,
        description="Уровень подтверждения записи",
    )
    producer_linger_ms: int = Field(
        ...,
        ge=0,
        le=10000,
        description="Задержка для батчинга сообщений",
    )

    # Безопасность
    security_protocol: Literal[
        "PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"
    ] = Field(
        ...,
        description="Протокол безопасности",
    )
    ca_bundle: Optional[Path] = Field(
        ...,
        description="Путь к CA сертификату",
    )
    username: Optional[Path] = Field(..., description="Логин")
    password: Optional[Path] = Field(..., description="Пароль")

    # Оптимизация
    compression_type: Literal["none", "gzip", "snappy", "lz4", "zstd"] = Field(
        ...,
        description="Тип сжатия сообщений",
    )
    message_max_bytes: int = Field(
        ...,
        ge=1,
        le=10000000,
        description="Максимальный размер сообщения",
    )

    # Таймауты
    session_timeout_ms: int = Field(
        ...,
        ge=1000,
        le=3600000,
        description="Таймаут сессии потребителя",
    )
    request_timeout_ms: int = Field(
        ...,
        ge=1000,
        le=3600000,
        description="Таймаут запросов к брокеру",
    )

    @field_validator("bootstrap_servers")
    @classmethod
    def validate_servers(cls, v):
        for server in v:
            if not re.match(r".+:\d+", server):
                raise ValueError(
                    "Некорректный формат адреса сервера (host:port)"
                )
        return v

    def get_kafka_config(self) -> Dict[str, Any]:
        """Преобразование настроек в конфиг для Kafka."""
        config = {
            "bootstrap.servers": ",".join(self.bootstrap_servers),
            "security.protocol": self.security_protocol,
            "compression.type": self.compression_type,
            "message.max.bytes": self.message_max_bytes,
            "session.timeout.ms": self.session_timeout_ms,
            "request.timeout.ms": self.request_timeout_ms,
        }

        # SSL конфигурация
        if self.ca_bundle:
            config.update({"ssl.ca.location": str(self.ca_bundle)})

        # SASL конфигурация
        if self.security_protocol in ("SASL_PLAINTEXT", "SASL_SSL"):
            config.update(
                {
                    "sasl.mechanism": "PLAIN",  # или SCRAM-SHA-256, OAUTHBEARER
                    "sasl.username": "your_username",  # замените на реальные значения
                    "sasl.password": "your_password",  # замените на реальные значения
                }
            )

        return config

    def get_kafka_producer_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию для Kafka Producer."""
        producer_config = {
            "acks": self.producer_acks,
            "linger.ms": self.producer_linger_ms,
        }
        return {**self.get_kafka_config(), **producer_config}

    def get_kafka_consumer_config(self) -> Dict[str, Any]:
        """Возвращает конфигурацию для Kafka Consumer."""
        consumer_config = {
            "group.id": self.consumer_group,
            "auto.offset.reset": self.auto_offset_reset,
            "max.poll.records": self.max_poll_records,
            "enable.auto.commit": False,
        }
        return {**self.get_kafka_config(), **consumer_config}


queue_settings = QueueSettings()
