from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from app.config.constants import ROOT_DIR


__all__ = ("DatabaseSettings",)


# Загрузка переменных окружения из файла .env
load_dotenv(ROOT_DIR / ".env")


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
        default="localhost",
        env="DB_HOST",
        description="Хост или IP-адрес сервера БД",
    )
    db_port: int = Field(
        default=5432,
        gt=0,
        lt=65536,
        env="DB_PORT",
        description="Порт сервера БД",
    )
    db_name: str = Field(
        default="postgres",
        env="DB_NAME",
        description="Имя базы данных или сервиса",
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
        default=10,
        ge=1,
        env="DB_POOL_SIZE",
        description="Размер пула соединений",
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
        default=None,
        env="DB_SSL_MODE",
        description="Режим SSL (для PostgreSQL)",
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
