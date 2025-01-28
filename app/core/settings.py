from pathlib import Path
from typing import Dict, List, Literal, Optional, Set

from dotenv import load_dotenv
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


ROOT_DIT = Path(__file__).parent.parent.parent

# Загрузка переменных окружения из файла .env
load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")


class APISSKBSettings(BaseSettings):
    """Настройки для работы с API СКБ-Техно.

    Attributes:
        skb_api_key (str): API ключ для доступа к API СКБ-Техно.
        skb_url (str): Базовый URL API СКБ-Техно.
        skb_endpoint (Dict[str, str]): Эндпоинты API СКБ-Техно.
        skb_request_priority_default (int): Приоритет запроса по умолчанию.
    """

    skb_api_key: str = Field(default="666-555-777", env="SKB_API_KEY")
    skb_url: str = Field(default="https://ya.ru/", env="SKB_URL")
    skb_endpoint: Dict[str, str] = {
        "GET_KINDS": "Kinds",
        "CREATE_REQUEST": "Create",
        "GET_RESULT": "Result",
    }
    skb_request_priority_default: int = Field(
        default=80, env="SKB_REQUEST_PRIORITY_DEFAULT"
    )


class APIDADATASettings(BaseSettings):
    """Настройки для работы с API Dadata.

    Attributes:
        dadata_api_key (str): API ключ для доступа к API Dadata.
        dadata_url (str): Базовый URL API Dadata.
        dadata_endpoint (Dict[str, str]): Эндпоинты API Dadata.
    """

    dadata_api_key: str = Field(default="666-2424-24", env="DADATA_API_KEY")
    dadata_url: str = Field(default="https://yap.ru/", env="DADATA_URL")
    dadata_endpoint: Dict[str, str] = {
        "GEOLOCATE": "geolocate/address",
    }


class DatabaseSettings(BaseSettings):
    """Настройки для подключения к базе данных.

    Attributes:
        db_type (Literal["postgresql", "oracle"]): Тип базы данных.
        db_host (str): Хост базы данных.
        db_port (int): Порт базы данных.
        db_name (str): Имя базы данных (или SID для Oracle).
        db_service_name (Optional[str]): Service name для Oracle.
        db_user (str): Пользователь базы данных.
        db_pass (str): Пароль пользователя.
        db_driver_async (str): Асинхронный драйвер (например, asyncpg, aioodbc).
        db_driver_sync (str): Синхронный драйвер (например, psycopg2, cx_oracle).
        db_echo (bool): Логирование SQL-запросов.
        db_connect_timeout (int): Таймаут подключения (секунды).
        db_command_timeout (int): Таймаут выполнения команды (секунды).
        db_pool_size (int): Размер пула соединений.
        db_max_overflow (int): Максимальное количество соединений сверх пула.
        db_pool_recycle (int): Пересоздавать соединения через N секунд.
        db_pool_timeout (int): Время ожидания соединения из пула (секунды).
        db_ssl_mode (Optional[str]): Режим SSL (для PostgreSQL).
        db_ssl_ca (Optional[str]): Путь к SSL CA сертификату.
    """

    db_type: Literal["postgresql", "oracle"] = Field(
        default="postgresql", env="DB_TYPE"
    )
    db_host: str = Field(default="localhost", env="DB_HOST")
    db_port: int = Field(default=5432, env="DB_PORT")
    db_name: str = Field(default="postgres", env="DB_NAME")
    db_service_name: Optional[str] = Field(default=None, env="DB_SERVICE_NAME")
    db_user: str = Field(default="postgres", env="DB_USER")
    db_pass: str = Field(default="postgres", env="DB_PASS")
    db_driver_async: str = Field(default="asyncpg", env="DB_DRIVER_ASYNC")
    db_driver_sync: str = Field(default="psycopg2", env="DB_DRIVER_SYNC")
    db_echo: bool = Field(default=False, env="DB_ECHO")
    db_connect_timeout: int = Field(default=10, env="DB_CONNECT_TIMEOUT")
    db_command_timeout: int = Field(default=30, env="DB_COMMAND_TIMEOUT")
    db_pool_size: int = Field(default=10, env="DB_POOL_SIZE")
    db_max_overflow: int = Field(default=10, env="DB_MAX_OVERFLOW")
    db_pool_recycle: int = Field(default=1800, env="DB_POOL_RECYCLE")
    db_pool_timeout: int = Field(default=30, env="DB_POOL_TIMEOUT")
    db_ssl_mode: Optional[str] = Field(default=None, env="DB_SSL_MODE")
    db_ssl_ca: Optional[str] = Field(default=None, env="DB_SSL_CA")

    @property
    def db_url_async(self) -> str:
        """URL для асинхронного подключения."""
        return self._build_url(is_async=True)

    @property
    def db_url_sync(self) -> str:
        """URL для синхронного подключения."""
        return self._build_url(is_async=False)

    def _build_url(self, is_async: bool) -> str:
        """Формирует URL подключения."""
        driver = self.db_driver_async if is_async else self.db_driver_sync

        if self.db_type == "postgresql":
            # Без параметра connect_timeout в URL
            url = f"postgresql+{driver}://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"
        elif self.db_type == "oracle":
            ...
        return url


class FileStorageSettings(BaseSettings):
    """Настройки для подключения к S3-совместимому хранилищу.

    Attributes:
        fs_provider: Literal["minio", "aws", "other"] - Тип провайдера
        fs_bucket: Имя бакета
        fs_endpoint: URL API хранилища
        fs_interface_url: URL веб-интерфейса
        fs_access_key: Ключ доступа
        fs_secret_key: Секретный ключ
        fs_region: Регион (для AWS)
        fs_secure: Использовать HTTPS
        fs_verify_tls: Проверять SSL сертификаты
        fs_ca_bundle: Путь к CA сертификату
        fs_timeout: Таймаут операций (сек)
        fs_retries: Число повторов
        fs_key_prefix: Префикс ключей
    """

    fs_provider: Literal["minio", "aws", "other"] = Field(
        default="minio", env="FS_PROVIDER"
    )
    fs_bucket: str = Field(default="my-bucket", env="FS_BUCKET")
    fs_endpoint: str = Field(default="http://127.0.0.1:9090", env="FS_ENDPOINT")
    fs_interface_url: str = Field(
        default="http://127.0.0.1:9091", env="FS_INTERFACE_URL"
    )
    fs_access_key: str = Field(default="minioadmin", env="FS_ACCESS_KEY")
    fs_secret_key: str = Field(default="minioadmin", env="FS_SECRET_KEY")
    fs_region: str = Field(default="us-east-1", env="FS_REGION")
    fs_secure: bool = Field(default=False, env="FS_SECURE")
    fs_verify_tls: bool = Field(default=False, env="FS_VERIFY_TLS")
    fs_ca_bundle: Optional[str] = Field(default=None, env="FS_CA_BUNDLE")
    fs_timeout: int = Field(default=30, env="FS_TIMEOUT")
    fs_retries: int = Field(default=3, env="FS_RETRIES")
    fs_key_prefix: str = Field(default="", env="FS_KEY_PREFIX")

    @property
    def normalized_endpoint(self) -> str:
        """Удаляет схему из endpoint для некоторых провайдеров"""
        return str(self.fs_endpoint).split("://")[-1]


class LogStorageSettings(BaseSettings):
    """Настройки для подключения к хранилищу логов.

    Attributes:
        log_host (str): Хост хранилища логов.
        log_port (int): Порт хранилища логов.
        log_udp_port (int): UDP порт для отправки логов.
        log_interface_url (str): URL интерфейса хранилища логов.
    """

    log_host: str = Field(default="http://127.0.0.1", env="LOG_HOST")
    log_port: int = Field(default=9000, env="LOG_PORT")
    log_udp_port: int = Field(default=12201, env="LOG_UDP_PORT")
    log_interface_url: str = Field(
        default="http://127.0.0.1:9000", env="LOG_INTERFACE_URL"
    )
    log_level: str = Field(default="DEBUG", env="LOG_LEVEL")
    log_file_path: str = Field(default="app.log", env="LOG_FILE_PATH")
    log_use_tls: bool = Field(default=False, env="LOG_USE_TLS")
    log_ca_certs: str | None = Field(default=None, env="LOG_CA_CERTS")
    log_required_fields: Set[str] | None = {
        "environment",
        "hostname",
        "user_id",
        "action",
    }

    @field_validator("log_udp_port", "log_port")
    @classmethod
    def validate_port(cls, v):
        if not 1 <= v <= 65535:
            raise ValueError("Port must be between 1 and 65535")
        return v

    @field_validator("log_level")
    @classmethod
    def validate_log_level(cls, v):
        v = v.upper()
        if v not in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            raise ValueError("Invalid log level")
        return v


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
    """Настройки для аутентификации.

    Attributes:
        auth_secret_key (str): Секретный ключ для аутентификации.
        auth_algorithm (str): Алгоритм шифрования токенов.
        auth_token_name (str): Имя токена аутентификации.
        auth_token_lifetime_seconds (int): Время жизни токена в секундах.
    """

    auth_secret_key: str = Field(default="your_secret_key", env="AUTH_SECRET_KEY")
    auth_algorithm: str = Field(default="HS256", env="AUTH_ALGORITHM")
    auth_token_name: str = Field(default="your_token_name", env="AUTH_TOKEN_NAME")
    auth_token_lifetime_seconds: int = Field(
        default=3600, env="AUTH_TOKEN_LIFETIME_SECONDS"
    )


class BackTasksSettings(BaseSettings):
    """Настройки для фоновых задач.

    Attributes:
        bts_interface_url (str): URL интерфейса для управления задачами.
        bts_max_time_limit (int): Максимальное время выполнения задачи.
        bts_min_retries (int): Минимальное количество попыток выполнения.
        bts_max_retries (int): Максимальное количество попыток выполнения.
        bts_min_retry_delay (int): Минимальная задержка между попытками.
        bts_max_retry_delay (int): Максимальная задержка между попытками.
        bts_expiration_time (int): Время истечения срока действия задачи.
    """

    bts_interface_url: str = Field(
        default="http://127.0.0.1:8888", env="BTS_INTERFACE_URL"
    )
    bts_max_time_limit: int = Field(default=300, env="BTS_MAX_TIME_LIMIT")
    bts_min_retries: int = Field(default=3, env="BTS_MIN_RETRIES")
    bts_max_retries: int = Field(default=5, env="BTS_MAX_RETRIES")
    bts_min_retry_delay: int = Field(default=30, env="BTS_MIN_RETRY_DELAY")
    bts_max_retry_delay: int = Field(default=300, env="BTS_MAX_RETRY_DELAY")
    bts_expiration_time: int = Field(default=1800, env="BTS_EXPIRATION_TIME")


class MailSettings(BaseSettings):
    """Настройки для отправки электронной почты.

    Attributes:
        mail_hostname (str): Хост SMTP сервера.
        mail_port (int): Порт SMTP сервера.
        mail_sender (str): Адрес отправителя.
        mail_login (str): Логин для авторизации на SMTP.
        mail_password (str): Пароль для авторизации на SMTP.
        mail_use_tls (bool): Флаг использования TLS для SMTP.
    """

    mail_hostname: str = Field(default="gd_advanced_tools.com", env="MAIL_HOSTNAME")
    mail_port: int = Field(default=586, env="MAIL_PORT")
    mail_sender: str = Field(default="example@kk.bank", env="MAIL_SENDER")
    mail_login: str = Field(default="gd_advanced_tools.com", env="MAIL_LOGIN")
    mail_password: str = Field(default="gd_advanced_tools.com", env="MAIL_PASSWORD")
    mail_use_tls: bool = False


class KafkaSettings(BaseSettings):
    """Настройки для работы с Apache Kafka.

    Attributes:
        kafka_bootstrap_servers (str): Список bootstrap-серверов Kafka.
        input_topic (str): Название основного входного топика.
        retry_topic (str): Название топика для повторной обработки.
        consumer_group_id (str): Идентификатор группы потребителей.
        auto_offset_reset (str): Стратегия выбора смещения (earliest/latest).
        enable_auto_commit (bool): Автоматическое подтверждение обработки.
        max_poll_interval_ms (int): Максимальное время между опросами.
        session_timeout_ms (int): Таймаут сессии потребителя.
        producer_acks (str): Уровень подтверждения для продюсера (all/0/1).
        producer_retries (int): Количество попыток повтора отправки.
        producer_linger_ms (int): Время задержки перед отправкой батча.
        security_protocol (str): Протокол безопасности (PLAINTEXT/SSL/SASL_SSL).
        ssl_cafile (Optional[str]): Путь к CA-сертификату.
        ssl_certfile (Optional[str]): Путь к сертификату клиента.
        ssl_keyfile (Optional[str]): Путь к приватному ключу клиента.
    """

    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", env="KAFKA_BOOTSTRAP_SERVERS"
    )
    input_topic: str = Field(
        default="kafka_input",
    )
    retry_topic: str = "retry_topic"
    auto_offset_reset: str = Field(default="earliest", env="KAFKA_AUTO_OFFSET_RESET")
    enable_auto_commit: bool = Field(default=False, env="KAFKA_ENABLE_AUTO_COMMIT")
    max_poll_interval_ms: int = Field(default=300000, env="KAFKA_MAX_POLL_INTERVAL_MS")
    session_timeout_ms: int = Field(default=10000, env="KAFKA_SESSION_TIMEOUT_MS")
    producer_acks: str = Field(default="all", env="KAFKA_PRODUCER_ACKS")
    producer_retries: int = Field(default=3, env="KAFKA_PRODUCER_RETRIES")
    producer_linger_ms: int = Field(default=5, env="KAFKA_PRODUCER_LINGER_MS")
    security_protocol: str = Field(default="PLAINTEXT", env="KAFKA_SECURITY_PROTOCOL")
    ssl_cafile: Optional[str] = Field(default=None, env="KAFKA_SSL_CAFILE")
    ssl_certfile: Optional[str] = Field(default=None, env="KAFKA_SSL_CERTFILE")
    ssl_keyfile: Optional[str] = Field(default=None, env="KAFKA_SSL_KEYFILE")


class Settings(BaseSettings):
    """Корневой класс настроек приложения.

    Объединяет все подсистемы настроек в единую конфигурацию.

    Attributes:
        root_dir (Path): Корневая директория проекта.
        base_url (str): Базовый URL приложения.
        app_version (str): Версия приложения.
        app_debug (bool): Флаг режима отладки.
        app_api_key (str): API ключ приложения.
        app_routes_without_api_key (List[str]): Маршруты без проверки API ключа.
        app_allowed_hosts (List[str]): Разрешенные хосты.
        app_cors_allowed_origins (List[str]): Разрешенные источники CORS.
        app_request_timeout (float): Таймаут запросов.
        app_rate_limit (int): Лимит запросов.
        app_rate_time_measure_seconds (int): Интервал измерения лимита.
        database_settings (DatabaseSettings): Настройки БД.
        api_skb_settings (APISSKBSettings): Настройки API СКБ.
        dadata_settings (APIDADATASettings): Настройки Dadata.
        logging_settings (LogStorageSettings): Настройки логов.
        storage_settings (FileStorageSettings): Настройки хранилища.
        redis_settings (RedisSettings): Настройки Redis.
        auth_settings (AuthSettings): Настройки аутентификации.
        bts_settings (BackTasksSettings): Настройки фоновых задач.
        mail_settings (MailSettings): Настройки почты.
        kafka_settings (KafkaSettings): Настройки Kafka.
    """

    app_root_dir: Path = ROOT_DIT
    app_base_url: str = Field(default="localhost:8000", env="APP_BASE_URL")
    app_environment: str = Field(default="development", env="APP_ENVIRONMENT")
    app_version: str = "0.1.0"
    app_debug: bool = Field(default=True, env="APP_DEBUG")
    app_api_key: str = Field(default="2f0-2340f", env="APP_API_KEY")
    app_routes_without_api_key: List[str] = [
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
    ]
    app_allowed_hosts: List[str] = [
        "example.com",
        "*.example.com",
        "localhost",
        "127.0.0.1",
    ]
    app_cors_allowed_origins: List[str] = ["*"]
    app_request_timeout: float = 50.0
    app_rate_limit: int = Field(default=100, env="APP_RATE_LIMIT")
    app_rate_time_measure_seconds: int = Field(
        default=60, env="APP_RATE_TIME_MEASURE_SECONDS"
    )

    database_settings: DatabaseSettings = DatabaseSettings()
    api_skb_settings: APISSKBSettings = APISSKBSettings()
    dadata_settings: APIDADATASettings = APIDADATASettings()
    logging_settings: LogStorageSettings = LogStorageSettings()
    storage_settings: FileStorageSettings = FileStorageSettings()
    redis_settings: RedisSettings = RedisSettings()
    auth_settings: AuthSettings = AuthSettings()
    bts_settings: BackTasksSettings = BackTasksSettings()
    mail_settings: MailSettings = MailSettings()
    kafka_settings: KafkaSettings = KafkaSettings()


# Экземпляр настроек приложения
settings = Settings()
