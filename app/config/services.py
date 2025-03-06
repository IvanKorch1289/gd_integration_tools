from pathlib import Path
from typing import ClassVar, Dict, List, Literal, Optional, Tuple

from pydantic import Field, computed_field, field_validator
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


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
    "TasksSettings",
    "tasks_settings",
    "GRPCSettings",
    "grpc_settings",
)


class FileStorageSettings(BaseSettingsWithLoader):
    """Настройки для подключения к S3-совместимому объектному хранилищу."""

    yaml_group: ClassVar[str] = "fs"
    model_config = SettingsConfigDict(env_prefix="FS_", extra="forbid")

    # Основные параметры подключения
    provider: Literal["minio", "aws", "other"] = Field(
        ...,
        description="Тип провайдера хранилища",
        example="minio",
    )
    bucket: str = Field(
        default="my-bucket",
        env="FS_BUCKET",
        description="Имя корзины по умолчанию",
        example="my-bucket",
    )
    access_key: str = Field(
        ...,
        description="Ключ доступа к хранилищу",
        example="AKIAIOSFODNN7EXAMPLE",
    )
    secret_key: str = Field(
        ...,
        description="Секретный ключ доступа к хранилищу",
        example="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )
    endpoint: str = Field(
        ...,
        description="URL API-эндпоинта хранилища",
        example="https://s3.example.com",
    )
    interface_endpoint: str = Field(
        ...,
        description="URL веб-интерфейса хранилища",
        example="https://console.s3.example.com",
    )

    # Параметры безопасности
    use_ssl: bool = Field(
        ...,
        description="Использовать HTTPS для подключений",
        example=True,
    )
    verify: bool = Field(
        ...,
        description="Проверять SSL-сертификаты",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        env="FS_CA_BUNDLE",
        description="Путь к пакету CA-сертификатов для SSL",
        example="/path/to/ca-bundle.crt",
    )

    # Параметры производительности
    timeout: int = Field(
        ...,
        description="Таймаут операций (в секундах)",
        example=30,
    )
    retries: int = Field(
        ...,
        description="Количество попыток для неудачных операций",
        example=3,
    )
    max_pool_connections: int = Field(
        ...,
        description="Максимальное количество соединений в пуле",
        example=50,
    )
    read_timeout: int = Field(
        ...,
        description="Таймаут чтения объектов (в секундах)",
        example=30,
    )

    # Параметры ключей
    key_prefix: str = Field(
        ...,
        description="Префикс для ключей объектов",
        example="my-prefix/",
    )

    @computed_field
    def normalized_endpoint(self) -> str:
        """Возвращает эндпоинт без схемы подключения (например, 'https://')."""
        return str(self.endpoint).split("://")[-1]


class LogStorageSettings(BaseSettingsWithLoader):
    """Настройки для системы логирования и хранения логов."""

    yaml_group: ClassVar[str] = "log"
    model_config = SettingsConfigDict(
        env_prefix="LOG_",
        extra="forbid",
    )

    # Параметры подключения
    host: str = Field(
        ...,
        description="Хост сервера логов",
        example="logs.example.com",
    )
    port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="TCP-порт сервера логов",
        example=514,
    )
    udp_port: int = Field(
        ...,
        gt=0,
        lt=65536,
        description="UDP-порт для отправки логов",
        example=514,
    )

    # Параметры безопасности
    use_tls: bool = Field(
        ...,
        description="Использовать TLS для безопасных подключений",
        example=True,
    )
    ca_bundle: Optional[str] = Field(
        default=None,
        description="Путь к пакету CA-сертификатов",
        example="/path/to/ca-bundle.crt",
    )

    # Параметры логирования
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        ...,
        pattern=r"^(DEBUG|INFO|WARNING|ERROR|CRITICAL)$",
        description="Уровень детализации логирования",
        example="INFO",
    )
    name_log_file: str = Field(
        ...,
        description="Путь к файлу логов",
        example="app.log",
    )
    dir_log_name: str = Field(
        ...,
        description="Имя директории для хранения логов",
        example="/var/logs/myapp",
    )
    required_fields: List[str] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Обязательные поля в лог-сообщениях",
        example={"timestamp", "level", "message"},
    )
    log_requests: bool = Field(
        ...,
        description="Включить логирование входящих запросов",
        example=True,
    )
    max_body_log_size: int = Field(
        ...,
        description="Максимальный размер лог-сообщений для логирования в байтах",
        example=1024 * 1024,  # 1MB
    )

    # Конфигурация логгеров
    conf_loggers: List[Dict] = Field(
        ...,
        default_factory=list,
        min_items=1,
        description="Конфигурация логгеров",
        example=[{"name": "application", "facility": "application"}],
    )

    @computed_field
    def base_url(self) -> str:
        """Создает нормализованную строку эндпоинта."""
        return f"{self.host}:{self.port}"


class RedisSettings(BaseSettingsWithLoader):
    """Настройки подключения к Redis."""

    yaml_group: ClassVar[str] = "redis"
    model_config = SettingsConfigDict(
        env_prefix="REDIS_",
        extra="forbid",
    )

    # Основные параметры подключения
    host: str = Field(
        ...,
        description="Хост или IP-адрес сервера Redis",
        example="redis.example.com",
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Порт сервера Redis",
        example=6379,
    )
    password: Optional[str] = Field(
        ...,
        description="Пароль для аутентификации в Redis",
        example="securepassword123",
    )
    encoding: str = Field(
        ...,
        description="Кодировка для сериализации данных",
        example="utf-8",
    )

    # Параметры баз данных
    db_cache: int = Field(
        ...,
        ge=0,
        description="Номер базы данных для кэширования",
        example=0,
    )
    db_queue: int = Field(
        ...,
        ge=0,
        description="Номер базы данных для управления очередями",
        example=1,
    )
    db_limits: int = Field(
        ...,
        ge=0,
        description="Номер базы данных для ограничений скорости",
        example=2,
    )
    db_tasks: int = Field(
        ..., ge=0, description="Номер базы данных для Celery", example=3
    )

    # Параметры производительности
    cache_expire_seconds: int = Field(
        ...,
        ge=60,
        description="Время жизни кэша по умолчанию в секундах",
        example=300,
    )
    max_connections: int = Field(
        ...,
        ge=1,
        description="Максимальное количество соединений в пуле",
        example=20,
    )
    socket_timeout: Optional[int] = Field(
        ...,
        ge=1,
        description="Таймаут операций с сокетом в секундах",
        example=10,
    )
    socket_connect_timeout: Optional[int] = Field(
        ...,
        ge=1,
        description="Таймаут установления соединения в секундах",
        example=5,
    )
    retry_on_timeout: Optional[bool] = Field(
        ...,
        description="Включить автоматический повтор при таймауте соединения",
        example=False,
    )
    socket_keepalive: Optional[bool] = Field(
        ..., description="Включить TCP keepalive для соединений", example=True
    )

    # Параметры безопасности
    use_ssl: bool = Field(
        ...,
        description="Включить SSL/TLS для безопасных соединений",
        example=False,
    )
    ca_bundle: Optional[str] = Field(
        ...,
        description="Путь к пакету CA-сертификатов для проверки SSL",
        example="/path/to/ca_bundle.crt",
    )

    # Параметры потоков
    main_stream: Optional[str] = Field(
        ..., description="Имя основного потока Redis", example="example-stream"
    )
    dlq_stream: Optional[str] = Field(
        ...,
        description="Имя потока DLQ Redis",
        example="dlq-example-stream",
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
        ...,
        description="Время хранения потоков Redis в часах",
        example=24,
    )
    max_retries: int = Field(
        ...,
        description="Максимальное количество попыток чтения сообщения в потоке",
        example=1,
    )
    ttl_hours: int = Field(
        ..., description="Время жизни сообщений в потоке", example=1
    )
    health_check_interval: int = Field(
        ..., description="Интервал проверки работоспособности", example=600
    )
    streams: List[Dict[str, str]] = Field(
        ...,
        min_items=1,
        description="Список потоков Redis",
        example=[
            {
                "name": "stream1",
                "value": "creating-stream",
            },
            {
                "name": "stream2",
                "value": "updating-stream",
            },
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
            raise ValueError(
                "Значение должно быть неотрицательным целым числом"
            )
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


class CelerySettings(BaseSettingsWithLoader):
    """Настройки для управления очередями задач и воркерами Celery."""

    yaml_group: ClassVar[str] = "celery"
    model_config = SettingsConfigDict(
        env_prefix="CELERY_",
        extra="forbid",
    )

    # Основные параметры
    redis_db: int = Field(
        ...,
        ge=0,
        description="Номер базы данных Redis для брокера Celery",
        example=0,
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
        ...,
        description="Отключить ограничение скорости для воркеров",
        example=False,
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
    flower_basic_auth: Optional[Tuple[str, str]] = Field(
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


class MailSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для сервиса электронной почты.

    Этот класс содержит параметры для настройки SMTP сервера, аутентификации, таймаутов и других параметров,
    связанных с отправкой электронной почты.
    """

    yaml_group: ClassVar[str] = "mail"
    model_config = SettingsConfigDict(
        env_prefix="MAIL_",
        extra="forbid",
    )

    # Блок настроек SMTP сервера
    host: str = Field(
        ..., description="Имя хоста SMTP сервера", example="smtp.example.com"
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Номер порта SMTP сервера",
        example=587,
    )
    use_tls: bool = Field(
        ...,
        description="Включить STARTTLS для безопасных соединений",
        example=True,
    )
    validate_certs: bool = Field(
        ..., description="Проверять SSL/TLS сертификаты сервера", example=True
    )
    ca_bundle: Optional[Path] = Field(
        ...,
        description="Путь к пользовательскому пакету CA сертификатов",
        example="/path/to/ca_bundle.crt",
    )

    # Блок настроек аутентификации
    username: str = Field(
        ...,
        description="Имя пользователя для аутентификации SMTP",
        example="user@example.com",
    )
    password: str = Field(
        ...,
        description="Пароль для аутентификации SMTP",
        example="securepassword123",
    )

    # Блок настроек таймаутов и пула соединений
    connection_pool_size: int = Field(
        ..., ge=1, le=20, description="Размер пула соединений SMTP", example=5
    )
    connect_timeout: int = Field(
        ...,
        ge=5,
        le=30,
        description="Таймаут подключения в секундах",
        example=30,
    )
    command_timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Таймаут сетевой операции в секундах",
        example=30,
    )

    # Блок настроек отправителя и шаблонов
    sender: str = Field(
        ...,
        description="Адрес электронной почты отправителя по умолчанию",
        example="noreply@example.com",
    )
    template_folder: Optional[Path] = Field(
        ...,
        description="Путь к директории с шаблонами писем",
        example="/app/email_templates",
    )

    # Блок настроек Circuit Breaker
    circuit_breaker_max_failures: int = Field(
        ...,
        ge=0,
        description="Максимальное количество сбоев до срабатывания Circuit Breaker",
        example=5,
    )
    circuit_breaker_reset_timeout: int = Field(
        ...,
        ge=0,
        description="Время (в секундах) до сброса Circuit Breaker",
        example=60,
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v, values):
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Порт 465 требует включения SSL/TLS")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v):
        if v and not v.exists():
            raise ValueError(f"Файл CA bundle не найден: {v}")
        return v


class QueueSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для брокера сообщений.

    Этот класс содержит параметры для настройки подключения к брокеру сообщений (Kafka или RabbitMQ),
    а также параметры для управления соединениями и аутентификации.
    """

    yaml_group: ClassVar[str] = "queue"
    model_config = SettingsConfigDict(
        env_prefix="QUEUE_",
        extra="forbid",
    )

    # Блок настроек типа и подключения к брокеру
    type: Literal["kafka", "rabbitmq"] = Field(
        ..., description="Тип брокера сообщений", example="kafka"
    )
    host: str = Field(
        ...,
        description="Имя хоста брокера",
        example="broker.example.com",
    )
    port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Номер порта брокера",
    )
    ui_port: int = Field(
        ...,
        ge=1,
        le=65535,
        description="Номер порта UI брокера",
        example=9121,
    )

    # Блок настроек таймаутов и повторных подключений
    timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Таймаут подключения к брокеру в секундах",
        example=30,
    )
    reconnect_interval: int = Field(
        ...,
        ge=5,
        le=300,
        description="Интервал между попытками повторного подключения в секундах",
        example=60,
    )

    # Блок настроек потребителей и graceful shutdown
    max_consumers: int = Field(
        ...,
        ge=1,
        description="Максимальное количество экземпляров потребителей",
        example=10,
    )
    graceful_timeout: int = Field(
        ...,
        ge=5,
        le=300,
        description="Таймаут graceful shutdown в секундах",
        example=60,
    )

    # Блок настроек SSL/TLS и аутентификации
    use_ssl: bool = Field(
        ...,
        description="Включить SSL/TLS для безопасных соединений",
        example=True,
    )
    ca_bundle: Optional[Path] = Field(
        ...,
        description="Путь к файлу CA сертификата",
        example="/path/to/ca.pem",
    )
    username: Optional[str] = Field(
        ...,
        description="Имя пользователя для аутентификации",
        example="kafka-user",
    )
    password: Optional[str] = Field(
        ...,
        description="Пароль для аутентификации",
        example="securepassword123",
    )

    # Блок настроек топиков
    topics: List[Dict[str, str]] = Field(
        ...,
        min_items=1,
        description="Список топиков",
        example=[
            {
                "name": "topic1",
                "value": "creating-topic",
            },
            {
                "name": "topic2",
                "value": "updating-topic",
            },
        ],
    )

    @field_validator("port")
    @classmethod
    def validate_port(cls, v, values):
        if v == 465 and not values.data.get("use_tls"):
            raise ValueError("Порт 465 требует включения SSL/TLS")
        return v

    @field_validator("ca_bundle")
    @classmethod
    def validate_ca_path(cls, v):
        if v and not v.exists():
            raise ValueError(f"Файл CA bundle не найден: {v}")
        return v

    @computed_field(description="Сформировать URL для подключения к очереди")
    def queue_url(self) -> str:
        """Сформировать URL для подключения к очереди."""
        return (
            f"amqp://{self.username}:{self.password}@{self.host}:{self.port}/"
        )

    @computed_field(
        description="Сформировать URL для подключения к UI очереди"
    )
    def queue_ui_url(self) -> str:
        """Сформировать URL для подключения к UI очереди."""
        return f"{self.host}:{self.ui_port}"

    def get_topic_name(self, topic_key: str) -> str:
        # Оптимизированный поиск с использованием генератора
        topic = next(
            (
                topic
                for topic in self.topics
                if topic.get("name", None) == topic_key
            ),
            None,
        )

        if not topic:
            raise ValueError(f"Не настроен топик для ключа: {topic_key}")

        return topic["value"]


class TasksSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для очереди задач и управления воркерами.

    Этот класс содержит параметры для настройки максимального количества попыток выполнения задач,
    задержек, таймаутов и других параметров, связанных с обработкой задач.
    """

    yaml_group: ClassVar[str] = "tasks"
    model_config = SettingsConfigDict(
        env_prefix="TASKS_",
        extra="forbid",
    )

    # Блок настроек для задач
    task_max_attempts: int = Field(
        ...,
        description="Максимальное количество попыток выполнения задачи",
        example=5,
    )
    task_seconds_delay: int = Field(
        ...,
        description="Начальная задержка в секундах для задачи",
        example=60,
    )
    task_retry_jitter_factor: float = Field(
        ...,
        description="Фактор случайности для экспоненциального отката",
        example=0.5,
    )
    task_timeout_seconds: int = Field(
        ...,
        description="Максимальное время выполнения задачи в секундах",
        example=3600,
    )

    # Блок настроек для потоков (flows)
    flow_max_attempts: int = Field(
        ...,
        description="Максимальное количество попыток выполнения потока",
        example=5,
    )
    flow_seconds_delay: int = Field(
        ...,
        description="Начальная задержка в секундах для потока",
        example=60,
    )
    flow_retry_jitter_factor: float = Field(
        ...,
        description="Фактор случайности для экспоненциального отката",
        example=0.5,
    )
    flow_timeout_seconds: int = Field(
        ...,
        description="Максимальное время выполнения потока в секундах",
        example=3600,
    )


class GRPCSettings(BaseSettingsWithLoader):
    """
    Настройки конфигурации для gRPC сервисов.

    Этот класс содержит параметры для настройки пути к сокету и максимального количества воркеров.
    """

    yaml_group: ClassVar[str] = "grpc"
    model_config = SettingsConfigDict(
        env_prefix="GRPC_",
        extra="forbid",
    )

    # Блок настроек сокета и воркеров
    socket_path: str = Field(
        ...,
        description="Путь к файлу сокета gRPC",
        example="/tmp/grpc.sock",
    )
    max_workers: int = Field(
        ...,
        description="Максимальное количество процессов воркеров gRPC",
        example=10,
    )

    @computed_field(description="Сформировать URI для подключения к сокету")
    def socket_uri(self) -> str:
        """Сформировать URI для подключения к сокету."""
        return f"unix://{self.socket_path}"


# Instantiate settings for immediate use
fs_settings = FileStorageSettings()
"""Глобальные настройки файлового хранилища"""

log_settings = LogStorageSettings()
"""Глобальные настройки логирования"""

redis_settings = RedisSettings()
"""Глобальные настройки Redis"""

celery_settings = CelerySettings()
"""Глобальные настройки Celery"""

mail_settings = MailSettings()
"""Глобальные настройки подключения SMTP-сервера"""

queue_settings = QueueSettings()
"""Глобальные настройки подключения к очереди сообщений"""

tasks_settings = TasksSettings()
"""Глобальные настройки фоновых задач"""

grpc_settings = GRPCSettings()
"""Глобальные настройки GRPC-сервера"""
