import os
from pathlib import Path
from typing import Dict, List, Union

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings


# Загрузка переменных окружения из файла .env
load_dotenv()

# Определение корневого пути проекта
ROOT_PATH = Path(__file__).parent.parent.parent
BASE_URL = os.getenv("BASE_URL")


class APISSKBSettings(BaseSettings):
    """Класс настроек API СКБ-Техно.

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


class DatabaseSettings(BaseSettings):
    """Класс настроек соединения с БД.

    Attributes:
        db_host (str): Хост базы данных.
        db_port (int): Порт базы данных.
        db_name (str): Имя базы данных.
        db_user (str): Пользователь базы данных.
        db_pass (str): Пароль пользователя базы данных.
        db_echo (bool): Флаг для вывода SQL-запросов в лог.
        db_poolsize (int): Размер пула соединений.
        db_maxoverflow (int): Максимальное количество соединений сверх размера пула.
    """

    db_host: str = Field(default="localhost", env="DB_HOST")
    db_port: int = Field(default=5432, env="DB_PORT")
    db_name: str = Field(default="postgres", env="DB_NAME")
    db_user: str = Field(default="postgres", env="DB_USER")
    db_pass: str = Field(default="postgres", env="DB_PASS")
    db_echo: bool = Field(default=False, env="DB_ECHO")
    db_poolsize: int = Field(default=10)
    db_maxoverflow: int = Field(default=10)

    @property
    def db_url_asyncpg(self) -> str:
        """Возвращает URL для асинхронного подключения к базе данных с использованием asyncpg."""
        return f"postgresql+asyncpg://{self.db_user}:{self.db_pass}@{self.db_host}:{self.db_port}/{self.db_name}"


class FileStorageSettings(BaseSettings):
    """Класс настроек соединения с файловым хранилищем.

    Attributes:
        fs_bucket (str): Имя бакета в файловом хранилище.
        fs_endpoint (str): URL файлового хранилища.
        fs_interfase_url (str): URL интерфейса файлового хранилища.
        fs_access_key (str): Ключ доступа к файловому хранилищу.
        fs_secret_key (str): Секретный ключ доступа к файловому хранилищу.
    """

    fs_bucket: str = Field(default="my-bucket", env="FS_BUCKET")
    fs_endpoint: str = Field(default="http://127.0.0.1:9090", env="FS_URL")
    fs_interfase_url: str = Field(
        default="http://127.0.0.1:9091", env="FS_INTERFACE_URL"
    )
    fs_access_key: str = Field(default="minioadmin", env="FS_ACCESS_KEY")
    fs_secret_key: str = Field(default="minioadmin", env="FS_SECRET_KEY")


class LogStorageSettings(BaseSettings):
    """Класс настроек соединения с хранилищем логов.

    Attributes:
        log_host (str): Хост хранилища логов.
        log_port (int): Порт хранилища логов.
        log_udp_port (int): UDP порт для отправки логов.
        log_interfaсe_url (str): URL интерфейса хранилища логов.
    """

    log_host: str = Field(default="http://127.0.0.1", env="LOG_HOST")
    log_port: int = Field(default=9000, env="LOG_PORT")
    log_udp_port: int = Field(default=12201, env="LOG_UDP_PORT")
    log_interfaсe_url: str = Field(
        default="http://127.0.0.1:9000", env="LOG_INTERFACE_URL"
    )


class RedisSettings(BaseSettings):
    """Класс настроек соединения с Redis.

    Attributes:
        redis_host (str): Хост Redis.
        redis_port (int): Порт Redis.
        redis_db_cashe (int): Номер базы данных для кэширования.
        redis_db_queue (int): Номер базы данных для очередей.
        redis_pass (Union[str, None]): Пароль Redis.
        redis_encoding (str): Кодировка данных в Redis.
        redis_decode_responses (bool): Флаг декодирования ответов от Redis.
        redis_cache_expire_seconds (int): Время жизни кэша в секундах.
    """

    redis_host: str = Field(default="localhost", env="REDIS_HOST")
    redis_port: int = Field(default=6379, env="REDIS_PORT")
    redis_db_cashe: int = 0
    redis_db_queue: int = 1
    redis_pass: Union[str, None] = Field(default=None, env="REDIS_PASS")
    redis_encoding: str = Field(default="utf-8", env="REDIS_ENCODING")
    redis_decode_responses: bool = Field(default=True, env="REDIS_DECODE_RESPONSES")
    redis_cache_expire_seconds: int = 300


class AuthSettings(BaseSettings):
    """Класс настроек аутентификации.

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
    """Класс настроек для фоновых задач.

    Attributes:
        bts_interface_url (str): URL интерфейса для управления фоновыми задачами.
        bts_max_time_limit (int): Максимальное время выполнения задачи.
        bts_min_retries (int): Минимальное количество попыток выполнения задачи.
        bts_max_retries (int): Максимальное количество попыток выполнения задачи.
        bts_min_retry_delay (int): Минимальная задержка между попытками выполнения задачи.
        bts_max_retry_delay (int): Максимальная задержка между попытками выполнения задачи.
        bts_expiration_time (int): Время истечения срока действия задачи.
    """

    bts_interface_url: str = Field(
        default="http://127.0.0.1:8888", env="BTS_INTERFACE_URL"
    )
    bts_max_time_limit: int = Field(default=300, env="BTS_MAX_TIME_LIMIT")
    bts_min_retries: int = Field(default=3, env="BTS_MAX_RETRIES")
    bts_max_retries: int = Field(default=5, env="BTS_MAX_RETRIES")
    bts_min_retry_delay: int = Field(default=30, env="BTS_MIN_RETRY_DELAY")
    bts_max_retry_delay: int = Field(default=300, env="BTS_MAX_RETRY_DELAY")
    bts_expiration_time: int = Field(default=1800, env="BTS_EXPIRATION_TIME")


class MailSettings(BaseSettings):
    """Класс настроек для отправки электронной почты.

    Attributes:
        mail_hostname (str): Хост SMTP сервера.
        mail_port (int): Порт SMTP сервера.
        mail_sender (str): Адрес отправителя.
        mail_login (str): Логин для авторизации на SMTP сервере.
        mail_password (str): Пароль для авторизации на SMTP сервере.
        mail_use_tls (bool): Флаг использования TLS для SMTP.
    """

    mail_hostname: str = Field(default="gd_advanced_tools.com", env="MAIL_HOSTNAME")
    mail_port: int = Field(default=586, env="MAIL_PORT")
    mail_sender: str = Field(default="example@kk.bank", env="MAIL_SENDER")
    mail_login: str = Field(default="gd_advanced_tools.com", env="MAIL_LOGIN")
    mail_password: str = Field(default="gd_advanced_tools.com", env="MAIL_PASSWORD")
    mail_use_tls: bool = False


class Settings(BaseSettings):
    """Основной класс настроек приложения.

    Attributes:
        root_dir (Path): Корневая директория проекта.
        base_url (str): Базовый URL приложения.
        app_debug (bool): Флаг режима отладки.
        app_api_key (str): API ключ приложения.
        app_routes_without_api_key (List[str]): Список маршрутов, не требующих API ключа.
        app_allowed_hosts (List[str]): Список разрешенных хостов.
        app_request_timeout (float): Таймаут запросов в секундах.
        database_settings (DatabaseSettings): Настройки базы данных.
        api_skb_settings (APISSKBSettings): Настройки API СКБ-Техно.
        logging_settings (LogStorageSettings): Настройки хранилища логов.
        storage_settings (FileStorageSettings): Настройки файлового хранилища.
        redis_settings (RedisSettings): Настройки Redis.
        auth_settings (AuthSettings): Настройки аутентификации.
        bts_settings (BackTasksSettings): Настройки фоновых задач.
        mail_settings (MailSettings): Настройки отправки электронной почты.
    """

    root_dir: Path
    base_url: str = BASE_URL
    app_version: str = "0.0.1"
    app_debug: bool = Field(default=True, env="APP_DEBUG")
    app_api_key: str = Field(default="2f0-2340f", env="APP_API_KEY")
    app_routes_without_api_key: List[str] = [
        "/",
        "/admin",
        "/admin/*",
        "/docs",
        "/metrics",
        "/openapi.json",
        "/tech/healthcheck-*",  # Все healthcheck-роуты не требуют API-ключа
        "/tech/redirect-*"  # Все redirect-роуты не требуют API-ключа
        "/tech/version",  # Роут /tech/version не требует API-ключа
        # Роут /tech/config требует API-ключа (не включен в список исключений)
    ]
    app_allowed_hosts: List[str] = [
        "example.com",
        "*.example.com",
        "localhost",
        "127.0.0.1",
    ]
    app_cors_allowed_origins: List[str] = ["*"]
    app_request_timeout: float = 50.0

    database_settings: DatabaseSettings = DatabaseSettings()
    api_skb_settings: APISSKBSettings = APISSKBSettings()
    logging_settings: LogStorageSettings = LogStorageSettings()
    storage_settings: FileStorageSettings = FileStorageSettings()
    redis_settings: RedisSettings = RedisSettings()
    auth_settings: AuthSettings = AuthSettings()
    bts_settings: BackTasksSettings = BackTasksSettings()
    mail_settings: MailSettings = MailSettings()


# Создание экземпляра настроек
settings = Settings(root_dir=ROOT_PATH)
