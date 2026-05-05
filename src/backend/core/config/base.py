from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import Field, computed_field, model_validator
from pydantic_settings import SettingsConfigDict

from src.core.config.config_loader import BaseSettingsWithLoader
from src.core.config.constants import consts

__all__ = (
    "AppBaseSettings",
    "SchedulerSettings",
    "app_base_settings",
    "scheduler_settings",
)


class AppBaseSettings(BaseSettingsWithLoader):
    """Основные настройки приложения с валидацией окружения и конфигурацией компонентов.

    Наследует функциональность загрузки из YAML-конфигов и предоставляет:
    - Валидацию критических параметров приложения
    - Автоматическое построение URL компонентов
    - Контроль режимов работы системы
    - Интеграцию с инструментами мониторинга

    Исключения:
        ValidationError: При несоответствии значений заданным ограничениям
        RuntimeError: При конфликте настроек компонентов
    """

    yaml_group: ClassVar[str] = "app"
    model_config = SettingsConfigDict(
        env_prefix="APP_", extra="forbid", validate_default=True
    )

    # Режимы работы системы
    environment: Literal["development", "staging", "production"] = Field(
        ...,
        title="Окружение",
        description=(
            "Текущее окружение выполнения:\n"
            " - development: режим разработки с дополнительными проверками\n"
            " - staging: предпродакшн окружение\n"
            " - production: продакшн окружение"
        ),
        examples=["production"],
    )

    debug_mode: bool = Field(
        ...,
        title="Режим отладки",
        description="Активирует расширенное логирование и проверки (не для production!)",
        examples=[False],
    )

    # Сетевые настройки
    host: str = Field(
        ...,
        title="Хост приложения",
        min_length=3,
        max_length=253,
        description="Домен или IP-адрес для доступа к сервису",
        examples=["api.example.com", "127.0.0.1"],
    )

    port: int = Field(
        ...,
        title="Порт приложения",
        ge=1,
        le=65535,
        description="Основной порт для HTTP-запросов",
        examples=[8000, 8080],
    )

    # Параметры ASGI-сервера
    server: Literal["uvicorn", "granian"] = Field(
        default="uvicorn",
        title="ASGI-сервер",
        description=(
            "Выбор ASGI-сервера для запуска приложения:\n"
            " - uvicorn: предпочтительно для локальной разработки (поддерживает --reload)\n"
            " - granian: предпочтительно для production (Rust-реализация, быстрее)"
        ),
        examples=["uvicorn", "granian"],
    )

    workers: int = Field(
        default=1,
        title="Количество воркеров ASGI-сервера",
        ge=1,
        le=64,
        description=(
            "Число воркер-процессов ASGI-сервера. В development режиме всегда 1."
        ),
        examples=[1, 4, 8],
    )

    # Wave 7.5 — performance tuning ASGI-сервера.
    listen_backlog: int = Field(
        default=2048,
        title="Listen backlog",
        ge=64,
        le=65535,
        description=(
            "TCP listen backlog (granian/uvicorn). Поднимаем до 2048 для "
            "выдерживания пиковой нагрузки 1k+ RPS без drop'ов на accept-очереди."
        ),
        examples=[1024, 2048, 4096],
    )

    keep_alive_timeout: int = Field(
        default=30,
        title="Keep-Alive timeout (сек)",
        ge=1,
        le=600,
        description="Таймаут keep-alive соединений в секундах.",
    )

    granian_http: Literal["1", "2", "auto"] = Field(
        default="auto",
        title="Granian HTTP-режим",
        description=(
            "Версия HTTP в granian: '1' (HTTP/1.1), '2' (HTTP/2 only), 'auto' "
            "(ALPN-negotiation). Default 'auto' — рекомендуется для production."
        ),
    )

    granian_runtime_mode: Literal["auto", "mt", "st"] = Field(
        default="auto",
        title="Granian runtime mode",
        description=(
            "Режим Rust-runtime: 'st' — single-thread (low overhead для I/O-bound), "
            "'mt' — multi-thread (для CPU-bound), 'auto' — granian решает по нагрузке."
        ),
    )

    granian_runtime_threads: int = Field(
        default=1,
        title="Granian runtime threads",
        ge=1,
        le=64,
        description=(
            "Число Rust-потоков на воркер (имеет смысл при ``runtime_mode=mt``)."
        ),
    )

    granian_blocking_threads: int | None = Field(
        default=None,
        title="Granian blocking threads",
        ge=1,
        le=256,
        description=(
            "Размер blocking thread pool на воркер для sync-вставок "
            "(sync DB-driver, file I/O). ``None`` — granian default."
        ),
    )

    langfuse_url: str = Field(
        default="",
        title="URL LangFuse",
        description="URL LangFuse Dashboard для мониторинга LLM-вызовов",
        examples=["http://localhost:3000"],
    )

    langgraph_url: str = Field(
        default="",
        title="URL LangGraph Studio",
        description="URL LangGraph Studio для управления AI-агентами",
        examples=["http://localhost:8123"],
    )

    use_ssl: bool = Field(
        ...,
        title="Использование SSL",
        description="Использовать SSL для безопасного соединения",
        examples=[True],
    )

    # Параметры сокетов
    socket_ping_timeout: int = Field(
        ...,
        title="Таймаут опроса сокетов",
        ge=1,
        description="Таймаут опроса сокетов в секундах",
        examples=[10, 60],
    )
    socket_close_timeout: int = Field(
        ...,
        title="Таймаут закрытия сокетов",
        ge=1,
        description="Таймаут закрытия сокетов в секундах",
        examples=[10, 60],
    )

    # Параметры GZIP
    gzip_minimum_size: int = Field(
        ...,
        title="Минимальный размер запроса для GZIP",
        ge=0,
        description="Минимальный размер запроса, при котором GZIP будет использоваться",
        examples=[500, 1000],
    )
    gzip_compresslevel: int = Field(
        ..., title="Уровень сжатия GZIP", ge=1, le=9, description="Уровень сжатия GZIP"
    )

    # Контроль документации
    enable_swagger: bool = Field(
        ...,
        title="Доступ к Swagger UI",
        description="Активирует интерфейс /docs (не рекомендуется для production)",
        examples=[True],
    )

    enable_redoc: bool = Field(
        ...,
        title="Доступ к ReDoc",
        description="Активирует альтернативную документацию /redoc",
        examples=[False],
    )

    # Телеметрия
    telemetry_enabled: bool = Field(
        ...,
        title="Сбор телеметрии",
        description="Активирует отправку метрик в OpenTelemetry",
        examples=[True],
    )

    opentelemetry_endpoint: str = Field(
        ...,
        title="OTLP эндпоинт",
        description="URL для экспорта телеметрии в формате OTLP",
        examples=["http://localhost:4317"],
    )

    # Администрирование
    admin_enabled: bool = Field(
        ...,
        title="Админ-панель",
        description="Активирует интерфейс администратора /admin",
        examples=[True],
    )

    monitoring_enabled: bool = Field(
        ...,
        title="Мониторинг",
        description="Активирует метрики Prometheus и healthchecks",
        examples=[True],
    )

    # Системные параметры
    version: str = Field(
        ...,
        title="Версия приложения",
        pattern=r"^\d+\.\d+\.\d+(-[a-zA-Z0-9]+)?$",
        description="Версия в формате SemVer (major.minor.patch[-prerelease])",
        examples=["1.0.0", "2.3.4-rc1"],
    )

    title: str = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Общий заголовок для всех страниц приложения",
        examples=["My Application", "API Server"],
    )

    root_dir: Path = Field(
        consts.ROOT_DIR,
        title="Корневая директория",
        description="Абсолютный путь к корню проекта",
        examples=["/opt/app", "C:/Projects/app"],
    )

    # Вычисляемые свойства

    @computed_field(description="Базовый URL приложения")
    def base_url(self) -> str:
        """Полный базовый URL вида ``scheme://host:port``."""
        return f"{self.build_base_url}:{self.port}"

    # Валидация бизнес-правил
    @model_validator(mode="after")
    def check_debug_mode(self) -> "AppBaseSettings":
        """Запрещает debug_mode=True в production-окружении."""
        if self.environment == "production" and self.debug_mode:
            raise ValueError("Режим отладки запрещен в production!")
        return self

    # Собрать базовый URL (без порта)
    @property
    def build_base_url(self) -> str:
        """Возвращает ``scheme://host`` без порта (на основе ``use_ssl``)."""
        return f"{'https://' if self.use_ssl else 'http://'}{self.host}"


class SchedulerSettings(BaseSettingsWithLoader):
    """Конфигурация планировщика задач с расширенной валидацией параметров.

    Обеспечивает:
    - Контроль параметров выполнения задач
    - Валидацию временных зон
    - Настройку обработки ошибок
    - Управление резервированием

    Исключения:
        ValueError: При некорректных настройках хранилища задач
        pytz.exceptions.UnknownTimeZoneError: При неверной временной зоне
    """

    yaml_group: ClassVar[str] = "scheduler"
    model_config = SettingsConfigDict(
        env_prefix="SCHEDULER_", extra="forbid", validate_default=True
    )

    # Хранилища задач
    default_jobstore_name: Literal["default", "backup"] = Field(
        ...,
        title="Основное хранилище",
        description="Имя основного хранилища задач",
        examples=["default"],
    )

    backup_jobstore_name: Literal["default", "backup"] = Field(
        ...,
        title="Резервное хранилище",
        description="Имя хранилища для резервного копирования задач",
        examples=["backup"],
    )

    # Параметры выполнения
    executors: dict[str, dict[str, Any]] = Field(
        ...,
        title="Исполнители задач",
        description="Конфигурация исполнителей для разных типов задач",
        examples=[
            {
                "fast": {"type": "processpool", "max_workers": 4},
                "slow": {"type": "threadpool", "max_workers": 10},
            }
        ],
    )

    misfire_grace_time: int = Field(
        ...,
        title="Допуск опоздания",
        ge=0,
        description="Максимальное опоздание выполнения задачи (в секундах)",
        examples=[300],
    )

    max_instances: int = Field(
        ...,
        title="Максимум экземпляров",
        ge=1,
        description="Максимальное количество одновременно выполняемых задач",
        examples=[5],
    )

    coalesce: bool = Field(
        ...,
        title="Объединение задач",
        description="Объединять повторные запуски одной задачи",
        examples=[True],
    )

    # Временные настройки
    timezone: str = Field(
        ...,
        title="Временная зона",
        description="Временная зона в формате IANA (например, Europe/Moscow)",
        examples=["UTC"],
    )

    @model_validator(mode="after")
    def check_jobstores(self) -> "SchedulerSettings":
        """Запрещает совпадение основного и резервного jobstore."""
        if self.default_jobstore_name == self.backup_jobstore_name:
            raise ValueError("Основное и резервное хранилища не могут совпадать!")
        return self


# Предварительно инициализированные конфигурации
app_base_settings: AppBaseSettings = AppBaseSettings()
"""Глобальный экземпляр настроек приложения"""

scheduler_settings: SchedulerSettings = SchedulerSettings()
"""Глобальный экземпляр настроек планировщика"""
