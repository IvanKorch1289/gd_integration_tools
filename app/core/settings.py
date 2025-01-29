import re
from pathlib import Path
from typing import Dict, List, Literal, Optional, Set, Tuple

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


ROOT_DIT = Path(__file__).parent.parent.parent

# Загрузка переменных окружения из файла .env
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class APISSKBSettings(BaseSettings):
    """Настройки интеграции с API СКБ-Техно.

    Группы параметров:
    - Авторизация: ключ API и базовый URL
    - Конфигурация запросов: эндпоинты и приоритеты
    - Таймауты: настройки времени ожидания
    """

    # Авторизация
    skb_api_key: str = Field(
        default="666-555-777",
        env="SKB_API_KEY",
        description="Секретный ключ для доступа к API СКБ-Техно",
    )
    skb_base_url: str = Field(
        default="https://ya.ru/",
        env="SKB_URL",
        description="Базовый URL API сервиса (без указания эндпоинтов)",
    )

    # Конфигурация запросов
    skb_endpoints: Dict[str, str] = Field(
        default={
            "GET_KINDS": "Kinds",
            "CREATE_REQUEST": "Create",
            "GET_RESULT": "Result",
        },
        description="Словарь эндпоинтов API (относительные пути)",
    )
    skb_default_priority: int = Field(
        default=80,
        ge=1,
        le=100,
        env="SKB_REQUEST_PRIORITY_DEFAULT",
        description="Приоритет запроса по умолчанию (1-100)",
    )

    # Таймауты
    skb_connect_timeout: float = Field(
        default=10.0, description="Максимальное время установки соединения (секунды)"
    )
    skb_read_timeout: float = Field(
        default=30.0, description="Максимальное время ожидания ответа (секунды)"
    )


class APIDADATASettings(BaseSettings):
    """Настройки интеграции с API Dadata.

    Группы параметров:
    - Авторизация: ключ API и базовый URL
    - Геолокация: параметры запросов геопозиционирования
    - Лимиты: ограничения на использование API
    """

    # Авторизация
    dadata_api_key: str = Field(
        default="666-2424-24",
        env="DADATA_API_KEY",
        description="Секретный ключ для доступа к API Dadata",
    )
    dadata_base_url: str = Field(
        default="https://yap.ru/",
        env="DADATA_URL",
        description="Базовый URL API сервиса (без указания эндпоинтов)",
    )

    # Геолокация
    dadata_endpoints: Dict[str, str] = Field(
        default={
            "GEOLOCATE": "geolocate/address",
        },
        description="Словарь эндпоинтов API (относительные пути)",
    )
    dadata_geolocate_radius: int = Field(
        default=100, description="Радиус поиска в метрах по умолчанию"
    )

    # Лимиты
    dadata_max_requests_per_second: int = Field(
        default=10, description="Максимальное количество запросов в секунду"
    )


class DatabaseSettings(BaseSettings):
    """Настройки подключения к реляционным базам данных.

    Группы параметров:
    - Основные параметры подключения
    - Аутентификация
    - Драйверы и режимы работы
    - Таймауты соединений
    - Пул соединений
    - SSL/TLS настройки
    """

    # Основные параметры
    db_type: Literal["postgresql", "oracle"] = Field(
        default="postgresql",
        env="DB_TYPE",
        description="Тип СУБД: postgresql или oracle",
    )
    db_host: str = Field(
        default="localhost", env="DB_HOST", description="Хост или IP-адрес сервера БД"
    )
    db_port: int = Field(
        default=5432, gt=0, lt=65536, env="DB_PORT", description="Порт сервера БД"
    )
    db_name: str = Field(
        default="postgres", env="DB_NAME", description="Имя базы данных или сервиса"
    )

    # Аутентификация
    db_user: str = Field(
        default="postgres", env="DB_USER", description="Имя пользователя БД"
    )
    db_pass: str = Field(
        default="postgres", env="DB_PASS", description="Пароль пользователя БД"
    )
    db_service_name: Optional[str] = Field(
        default=None,
        env="DB_SERVICE_NAME",
        description="Имя сервиса Oracle (только для Oracle)",
    )

    # Драйверы и режимы
    db_driver_async: str = Field(
        default="asyncpg",
        env="DB_DRIVER_ASYNC",
        description="Асинхронный драйвер (asyncpg/aioodbc)",
    )
    db_driver_sync: str = Field(
        default="psycopg2",
        env="DB_DRIVER_SYNC",
        description="Синхронный драйвер (psycopg2/cx_oracle)",
    )
    db_echo: bool = Field(
        default=False, env="DB_ECHO", description="Логировать SQL-запросы"
    )

    # Таймауты
    db_connect_timeout: int = Field(
        default=10,
        env="DB_CONNECT_TIMEOUT",
        description="Таймаут подключения (секунды)",
    )
    db_command_timeout: int = Field(
        default=30,
        env="DB_COMMAND_TIMEOUT",
        description="Таймаут выполнения команд (секунды)",
    )

    # Пул соединений
    db_pool_size: int = Field(
        default=10, ge=1, env="DB_POOL_SIZE", description="Размер пула соединений"
    )
    db_max_overflow: int = Field(
        default=10,
        ge=0,
        env="DB_MAX_OVERFLOW",
        description="Максимальное количество соединений сверх пула",
    )
    db_pool_recycle: int = Field(
        default=1800,
        env="DB_POOL_RECYCLE",
        description="Время пересоздания соединений (секунды)",
    )
    db_pool_timeout: int = Field(
        default=30,
        env="DB_POOL_TIMEOUT",
        description="Таймаут ожидания соединения из пула (секунды)",
    )

    # SSL/TLS
    db_ssl_mode: Optional[str] = Field(
        default=None, env="DB_SSL_MODE", description="Режим SSL (для PostgreSQL)"
    )
    db_ssl_ca: Optional[str] = Field(
        default=None, env="DB_SSL_CA", description="Путь к SSL CA сертификату"
    )

    @property
    def db_url_async(self) -> str:
        """Формирует DSN для асинхронного подключения."""
        return self._build_url(is_async=True)

    @property
    def db_url_sync(self) -> str:
        """Формирует DSN для синхронного подключения."""
        return self._build_url(is_async=False)

    def _build_url(self, is_async: bool) -> str:
        """Внутренний метод для построения DSN строки."""
        driver = self.db_driver_async if is_async else self.db_driver_sync

        if self.db_type == "postgresql":
            return (
                f"postgresql+{driver}://{self.db_user}:{self.db_pass}"
                f"@{self.db_host}:{self.db_port}/{self.db_name}"
            )
        elif self.db_type == "oracle":
            # Реализация для Oracle
            raise NotImplementedError("Oracle support is not implemented yet")
        return ""


class FileStorageSettings(BaseSettings):
    """Настройки подключения к S3-совместимому объектному хранилищу.

    Группы параметров:
    - Основные параметры хранилища
    - Аутентификация
    - Параметры подключения
    - Настройки SSL/TLS
    - Политики повторов
    - Управление ключами
    """

    # Основные параметры
    fs_provider: Literal["minio", "aws", "other"] = Field(
        default="minio", env="FS_PROVIDER", description="Тип провайдера хранилища"
    )
    fs_bucket: str = Field(
        default="my-bucket", env="FS_BUCKET", description="Имя бакета по умолчанию"
    )

    # Аутентификация
    fs_access_key: str = Field(
        default="minioadmin",
        env="FS_ACCESS_KEY",
        description="Ключ доступа к хранилищу",
    )
    fs_secret_key: str = Field(
        default="minioadmin", env="FS_SECRET_KEY", description="Секретный ключ доступа"
    )

    # Параметры подключения
    fs_endpoint: str = Field(
        default="http://127.0.0.1:9090",
        env="FS_ENDPOINT",
        description="URL API хранилища",
    )
    fs_region: str = Field(
        default="us-east-1", env="FS_REGION", description="Регион хранилища (для AWS)"
    )
    fs_secure: bool = Field(
        default=False, env="FS_SECURE", description="Использовать HTTPS соединение"
    )

    # Настройки SSL/TLS
    fs_verify_tls: bool = Field(
        default=False, env="FS_VERIFY_TLS", description="Проверять SSL сертификаты"
    )
    fs_ca_bundle: Optional[str] = Field(
        default=None, env="FS_CA_BUNDLE", description="Путь к CA сертификату для SSL"
    )

    # Политики повторов
    fs_timeout: int = Field(
        default=30, env="FS_TIMEOUT", description="Таймаут операций (секунды)"
    )
    fs_retries: int = Field(
        default=3, env="FS_RETRIES", description="Количество попыток при ошибках"
    )

    # Управление ключами
    fs_key_prefix: str = Field(
        default="", env="FS_KEY_PREFIX", description="Префикс для ключей объектов"
    )

    @property
    def normalized_endpoint(self) -> str:
        """Возвращает endpoint без схемы подключения."""
        return str(self.fs_endpoint).split("://")[-1]


class LogStorageSettings(BaseSettings):
    """Настройки системы логирования и хранения логов.

    Группы параметров:
    - Основные параметры подключения
    - Настройки безопасности
    - Параметры формата логов
    - Валидация логов
    """

    # Основные параметры
    log_host: str = Field(
        default="http://127.0.0.1", env="LOG_HOST", description="Хост сервера логов"
    )
    log_port: int = Field(
        default=9000,
        gt=0,
        lt=65536,
        env="LOG_PORT",
        description="TCP порт сервера логов",
    )
    log_udp_port: int = Field(
        default=12201,
        gt=0,
        lt=65536,
        env="LOG_UDP_PORT",
        description="UDP порт для отправки логов",
    )

    # Настройки безопасности
    log_use_tls: bool = Field(
        default=False, env="LOG_USE_TLS", description="Использовать TLS для подключения"
    )
    log_ca_certs: Optional[str] = Field(
        default=None, env="LOG_CA_CERTS", description="Путь к CA сертификату"
    )

    # Параметры формата
    log_level: str = Field(
        default="DEBUG", env="LOG_LEVEL", description="Уровень детализации логов"
    )
    log_file_path: str = Field(
        default="app.log", env="LOG_FILE_PATH", description="Путь к файлу логов"
    )

    # Валидация логов
    log_required_fields: Set[str] = Field(
        default={"environment", "hostname", "user_id", "action"},
        description="Обязательные поля в лог-сообщениях",
    )

    @field_validator("log_udp_port", "log_port")
    @classmethod
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        allowed_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in allowed_levels:
            raise ValueError(f"Invalid log level. Allowed: {allowed_levels}")
        return v.upper()


class RedisSettings(BaseSettings):
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

    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db_cache: int = 0
    redis_db_queue: int = 1
    redis_db_limits: int = 2
    redis_pass: Optional[str] = Field(default=None, env="REDIS_PASS")
    redis_encoding: str = Field(default="utf-8", env="REDIS_ENCODING")
    redis_decode_responses: bool = Field(default=True, env="REDIS_DECODE_RESPONSES")
    redis_cache_expire_seconds: int = 300
    redis_connect_timeout: int = Field(default=5, env="REDIS_CONNECT_TIMEOUT")
    redis_timeout: int = Field(default=10, env="REDIS_TIMEOUT")
    redis_pool_maxsize: int = Field(default=20, env="REDIS_POOL_MAXSIZE")
    redis_pool_minsize: int = Field(default=5, env="REDIS_POOL_MINSIZE")
    redis_use_ssl: bool = Field(default=False, env="REDIS_USE_SSL")
    redis_ssl_ca_certs: Optional[str] = Field(default=None, env="REDIS_SSL_CA_CERTS")
    redis_retries: int = Field(default=3, env="REDIS_RETRIES")
    redis_retry_delay: int = Field(default=1, env="REDIS_RETRY_DELAY")

    @property
    def redis_url(self) -> str:
        """Сформировать URL для подключения к Redis."""
        protocol = "rediss" if self.redis_use_ssl else "redis"
        return f"{protocol}://{self.redis_host}:{self.redis_port}"


class AuthSettings(BaseSettings):
    """Настройки системы аутентификации и авторизации.

    Группы параметров:
    - Основные параметры токена
    - Алгоритмы и ключи
    - Дополнительные настройки
    """

    # Основные параметры токена
    auth_token_name: str = Field(
        default="access_token",
        env="AUTH_TOKEN_NAME",
        description="Имя HTTP-куки/заголовка с токеном",
    )
    auth_token_lifetime: int = Field(
        default=3600,
        ge=60,
        env="AUTH_TOKEN_LIFETIME_SECONDS",
        description="Время жизни токена в секундах (мин. 60)",
    )
    auth_refresh_token_lifetime: int = Field(
        default=2592000,
        ge=3600,
        env="AUTH_REFRESH_TOKEN_LIFETIME_SECONDS",
        description="Время жизни refresh-токена в секундах (по умолчанию 30 дней)",
    )

    # Алгоритмы и ключи
    auth_secret_key: str = Field(
        default="your_secret_key",
        env="AUTH_SECRET_KEY",
        min_length=32,
        description="Секретный ключ для подписи токенов (мин. 32 символа)",
    )
    auth_algorithm: Literal["HS256", "HS384", "HS512", "RS256"] = Field(
        default="HS256", env="AUTH_ALGORITHM", description="Алгоритм подписи токенов"
    )

    # Дополнительные настройки
    auth_cookie_secure: bool = Field(
        default=False,
        env="AUTH_COOKIE_SECURE",
        description="Передавать токен только по HTTPS",
    )
    auth_cookie_samesite: Literal["lax", "strict", "none"] = Field(
        default="lax",
        env="AUTH_COOKIE_SAMESITE",
        description="Политика SameSite для cookie",
    )

    @field_validator("auth_algorithm")
    @classmethod
    def validate_algorithm(cls, v):
        if v.startswith("HS") and "secret_key" in cls.model_fields:
            if len(cls.auth_secret_key) < 32:
                raise ValueError("HS алгоритмы требуют ключ минимум 32 символа")
        return v


class CelerySettings(BaseSettings):
    """Настройки для Celery (фоновые задачи и воркеры).

    Группы параметров:
    - Подключение к брокеру
    - Поведение задач
    - Конфигурация воркеров
    - Мониторинг и трекинг
    - Оптимизация производительности
    """

    # Подключение к брокеру
    cel_broker_url: str = Field(
        default="redis://localhost:6379/0",
        env="CELERY_BROKER_URL",
        description="URL брокера сообщений (redis://, amqp://, sqs://)",
    )
    cel_result_backend: str = Field(
        default="redis://localhost:6379/1",
        env="CELERY_RESULT_BACKEND",
        description="URL бэкенда для результатов задач",
    )

    # Поведение задач
    cel_task_default_queue: str = Field(
        default="default",
        env="CELERY_TASK_DEFAULT_QUEUE",
        description="Очередь по умолчанию для задач",
    )
    cel_task_serializer: Literal["json", "pickle", "yaml", "msgpack"] = Field(
        default="json",
        env="CELERY_TASK_SERIALIZER",
        description="Сериализатор для задач",
    )
    cel_task_time_limit: int = Field(
        default=300,
        ge=60,
        env="CELERY_TASK_TIME_LIMIT",
        description="Максимальное время выполнения задачи (секунды)",
    )
    cel_task_soft_time_limit: int = Field(
        default=240,
        env="CELERY_TASK_SOFT_TIME_LIMIT",
        description="Мягкий таймаут перед отправкой SIGTERM",
    )
    cel_task_max_retries: int = Field(
        default=3,
        ge=0,
        env="CELERY_TASK_MAX_RETRIES",
        description="Максимальное количество повторных попыток",
    )
    cel_task_retry_backoff: int = Field(
        default=60,
        end="CELERY_TASK_RETRY_BACKOFF",
        description="Базовая задержка перед повтором (секунды)",
    )
    cel_task_retry_jitter: bool = Field(
        default=True,
        env="CELERY_TASK_RETRY_JITTER",
        description="Добавлять случайный джиттер к задержке",
    )

    # Конфигурация воркеров
    cel_worker_concurrency: int = Field(
        default=4,
        ge=1,
        env="CELERY_WORKER_CONCURRENCY",
        description="Количество параллельных процессов воркера",
    )
    cel_worker_prefetch_multiplier: int = Field(
        default=4,
        env="CELERY_WORKER_PREFETCH_MULTIPLIER",
        description="Множитель предварительной выборки задач",
    )
    cel_worker_max_tasks_per_child: int = Field(
        default=100,
        env="CELERY_WORKER_MAX_TASKS_PER_CHILD",
        description="Максимум задач до перезапуска процесса",
    )
    cel_worker_disable_rate_limits: bool = Field(
        default=False,
        env="CELERY_WORKER_DISABLE_RATE_LIMITS",
        description="Отключить лимиты скорости выполнения",
    )

    # Мониторинг
    cel_flower_url: str = Field(
        default="http://localhost:8887",
        env="CELERY_FLOWER_URL",
        description="Адрес веб-интерфейса Flower",
    )
    cel_flower_basic_auth: Tuple[str, str] | None = Field(
        default=None,
        env="CELERY_FLOWER_BASIC_AUTH",
        description="Логин/пароль для Flower в формате (user, password)",
    )
    cel_task_track_started: bool = Field(
        default=True,
        env="CELERY_TASK_TRACK_STARTED",
        description="Отслеживать статус STARTED для задач",
    )

    # Оптимизация
    cel_broker_pool_limit: int = Field(
        default=10,
        env="CELERY_BROKER_POOL_LIMIT",
        description="Максимум соединений с брокером",
    )
    cel_result_extended: bool = Field(
        default=False,
        env="CELERY_RESULT_EXTENDED",
        description="Хранить расширенные метаданные результатов",
    )
    cel_worker_send_events: bool = Field(
        default=True,
        env="CELERY_WORKER_SEND_EVENTS",
        description="Отправлять события для мониторинга",
    )

    @field_validator("cel_flower_basic_auth")
    @classmethod
    def validate_auth(cls, v):
        if v and len(v) != 2:
            raise ValueError("Auth must be tuple of (username, password)")
        return v

    @property
    def task_retry_policy(self) -> dict:
        """Сформировать политику повторных попыток для задач."""
        return {
            "max_retries": self.task_max_retries,
            "interval_start": self.task_retry_backoff,
            "jitter": self.task_retry_jitter,
        }


class MailSettings(BaseSettings):
    """Настройки электронной почты.

    Группы параметров:
    - Параметры сервера
    - Аутентификация
    - Настройки TLS
    - Параметры писем
    """

    # Параметры сервера
    mail_host: str = Field(
        default="smtp.example.com",
        env="MAIL_HOST",
        description="SMTP сервер для отправки почты",
    )
    mail_port: int = Field(
        default=587, ge=1, le=65535, env="MAIL_PORT", description="Порт SMTP сервера"
    )

    # Аутентификация
    mail_username: str = Field(
        default="user@example.com",
        env="MAIL_USERNAME",
        description="Логин для SMTP аутентификации",
    )
    mail_password: str = Field(
        default="password",
        env="MAIL_PASSWORD",
        description="Пароль для SMTP аутентификации",
    )

    # Настройки TLS
    mail_use_tls: bool = Field(
        default=True,
        env="MAIL_USE_TLS",
        description="Использовать STARTTLS для шифрования",
    )
    mail_validate_certs: bool = Field(
        default=True,
        env="MAIL_VALIDATE_CERTS",
        description="Проверять SSL сертификаты сервера",
    )

    # Параметры писем
    mail_sender: str = Field(
        default="noreply@example.com", description="Email отправителя по умолчанию"
    )
    mail_template_folder: Optional[Path] = Field(
        default=None, env="MAIL_TEMPLATE_FOULDER", description="Путь к шаблонам писем"
    )

    @field_validator("mail_port")
    @classmethod
    def validate_port(cls, v):
        if v == 465 and not cls.mail_use_tls:
            raise ValueError("Порт 465 требует SSL/TLS")
        return v


class QueueSettings(BaseSettings):
    """Настройки брокера сообщений.

    Группы параметров:
    - Основные параметры
    - Настройки потребителя (Consumer)
    - Настройки производителя (Producer)
    - Безопасность
    - Оптимизация производительности
    - Таймауты и повторы
    """

    # Основные параметры
    queue_type: Literal["kafka", "rabbitmq"] = Field(
        default="kafka", env="QUEUE_TYPE", description="Тип брокера сообщений"
    )
    queue_bootstrap_servers: List[str] = Field(
        default=["localhost:9092"], description="Список серверов брокера"
    )

    # Настройки потребителя
    queue_consumer_group: str = Field(
        default="api-consumers", description="Группа потребителей (Kafka)"
    )
    queue_auto_offset_reset: Literal["earliest", "latest"] = Field(
        default="earliest", description="Поведение при отсутствии оффсета"
    )
    queue_max_poll_records: int = Field(
        default=500, ge=1, description="Максимальное количество записей за опрос"
    )

    # Настройки производителя
    queue_producer_acks: Literal["all", "0", "1"] = Field(
        default="all", description="Уровень подтверждения записи"
    )
    queue_producer_linger_ms: int = Field(
        default=5, description="Задержка для батчинга сообщений"
    )

    # Безопасность
    queue_security_protocol: Literal[
        "PLAINTEXT", "SSL", "SASL_PLAINTEXT", "SASL_SSL"
    ] = Field(default="PLAINTEXT", description="Протокол безопасности")
    queue_ssl_ca_location: Optional[Path] = Field(
        default=None, description="Путь к CA сертификату"
    )

    # Оптимизация
    queue_compression_type: Literal["none", "gzip", "snappy", "lz4", "zstd"] = Field(
        default="none", description="Тип сжатия сообщений"
    )
    queue_message_max_bytes: int = Field(
        default=1048576, description="Максимальный размер сообщения"
    )

    # Таймауты
    queue_session_timeout_ms: int = Field(
        default=10000, description="Таймаут сессии потребителя"
    )
    queue_request_timeout_ms: int = Field(
        default=40000, description="Таймаут запросов к брокеру"
    )

    @field_validator("queue_bootstrap_servers")
    @classmethod
    def validate_servers(cls, v):
        for server in v:
            if not re.match(r".+:\d+", server):
                raise ValueError("Некорректный формат адреса сервера (host:port)")
        return v


class Settings(BaseSettings):
    """Корневая конфигурация приложения.

    Объединяет все компоненты конфигурации:
    - Общие настройки приложения
    - Интеграции с внешними API
    - Настройки хранилищ данных
    - Системные компоненты
    """

    # Общие настройки
    app_root_dir: Path = ROOT_DIT
    app_base_url: str = Field(default="localhost:8000", env="APP_BASE_URL")
    app_environment: Literal["development", "staging", "production"] = Field(
        default="development",
        env="APP_ENVIRONMENT",
        description="Среда выполнения приложения",
    )
    app_version: str = Field(
        default="0.1.0",
        frozen=True,
        description="Версия приложения в семантическом формате",
    )
    app_debug: bool = Field(
        default=True,
        env="APP_DEBUG",
        description="Признак включенного режима дебаггинга",
    )

    # Безопасность
    app_api_key: str = Field(
        default="2f0-2340f",
        env="APP_API_KEY",
        description="Главный API-ключ приложения",
    )
    app_allowed_hosts: List[str] = Field(
        default=[
            "example.com",
            "*.example.com",
            "localhost",
            "127.0.0.1",
        ],
        description="Разрешенные хосты для входящих запросов",
    )
    app_routes_without_api_key: List[str] = Field(
        default=[
            "/",
            "/admin",
            "/admin/*",
            "/docs",
            "/documents",
            "/docs/",
            "/documents/",
            "/metrics",
            "/openapi.json",
            "/tech/healthcheck-*",
            "/tech/redirect-*",
            "/tech/version",
            "/tech/log-storage",
            "/tech/file-storage",
            "/tech/task-monitor",
        ],
        description="Эндпоинты с доступом без API-ключа приложения",
    )
    app_request_timeout: float = Field(
        default=5.0,
        env="APP_REQUEST_TIMEOUT",
        description="Максимальное время ожидания запроса (в секундах)",
    )
    app_rate_limit: int = Field(
        default=100,
        env="APP_RATE_LIMIT",
        description="Количество запросов в минуту, которое разрешено приложению",
    )
    app_rate_time_measure_seconds: int = Field(
        default=60,
        env="APP_RATE_TIME_MEASURE_SECONDS",
        description="Время измерения посещений (в секундах)",
    )

    # Интеграции
    database: DatabaseSettings = DatabaseSettings()

    skb_api: APISSKBSettings = APISSKBSettings()
    dadata_api: APIDADATASettings = APIDADATASettings()
    queue: QueueSettings = QueueSettings()
    mail: MailSettings = MailSettings()

    # Хранилища
    storage: FileStorageSettings = FileStorageSettings()
    logging: LogStorageSettings = LogStorageSettings()
    redis: RedisSettings = RedisSettings()

    # Прочее
    auth: AuthSettings = AuthSettings()
    celery: CelerySettings = CelerySettings()


# Экземпляр настроек приложения
settings = Settings()
