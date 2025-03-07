from typing import ClassVar, Dict, List

from pydantic import Field, model_validator
from pydantic_settings import SettingsConfigDict

from app.config.config_loader import BaseSettingsWithLoader


__all__ = (
    "SKBAPISettings",
    "skb_api_settings",
    "DadataAPISettings",
    "dadata_api_settings",
    "HttpBaseSettings",
    "http_base_settings",
)


class HttpBaseSettings(BaseSettingsWithLoader):
    """Базовые настройки HTTP-клиента для управления соединениями и таймаутами."""

    yaml_group: ClassVar[str] = "http"
    model_config = SettingsConfigDict(
        env_prefix="HTTP_",
        extra="forbid",
    )

    # Настройки повторных запросов
    max_retries: int = Field(
        ...,
        title="Максимум повторов",
        ge=0,
        description="Максимальное количество попыток повторных запросов",
        examples=[3],
    )

    retry_backoff_factor: float = Field(
        ...,
        title="Фактор задержки",
        ge=0,
        description="Множитель для экспоненциальной задержки между повторами",
        examples=[0.5],
    )

    retry_status_codes: List[int] = Field(
        ...,
        title="Статусы кода с повторным запросом",
        description="Список статусов кода, которые будут повторными попытками",
        examples=[500, 503],
    )

    # Таймауты соединений
    connect_timeout: int = Field(
        ...,
        title="Таймаут подключения",
        ge=1,
        description="Максимальное время установки соединения (секунды)",
        examples=[10],
    )

    total_timeout: int = Field(
        ...,
        title="Общий таймаут",
        ge=1,
        description="Общее максимальное время выполнения запроса",
        examples=[60],
    )

    sock_read_timeout: int = Field(
        ...,
        title="Таймаут чтения",
        ge=1,
        description="Максимальное время чтения ответа (секунды)",
        examples=[30],
    )

    keepalive_timeout: int = Field(
        ...,
        title="Таймаут keepalive",
        ge=1,
        description="Максимальное время ожидания keepalive-пакета (секунды)",
        examples=[60],
    )

    force_close: bool = Field(
        default=False,
        title="Принудительное закрытие соединения",
        description="При значении True принудительно закрывает соединения после завершения работы",
        examples=[False],
    )

    # Управление пулом соединений
    limit: int = Field(
        ...,
        title="Лимит соединений",
        ge=1,
        description="Максимальное общее количество соединений",
        examples=[100],
    )

    limit_per_host: int = Field(
        ...,
        title="Лимит на хост",
        ge=1,
        description="Максимум одновременных соединений с одним хостом",
        examples=[10],
    )

    enable_connection_purging: bool = Field(
        default=False,
        title="Включение очистки пула соединений",
        description="При значении True автоматически очищает пул соединений после определенного интервала",
        examples=[False],
    )

    purging_interval: int = Field(
        ...,
        title="Интервал очистки пула",
        ge=0,
        description="Интервал очистки пула соединений (в секундах)",
        examples=[600],
    )

    circuit_breaker_max_failures: int = Field(
        ...,
        title="Максимальное количество неудачных попыток",
        ge=0,
        description="Максимальное количество неудачных попыток до блокировки соединения",
        examples=[5, 10],
    )

    circuit_breaker_reset_timeout: int = Field(
        ...,
        title="Таймаут сброса неудачных попыток",
        ge=0,
        description="Таймаут сброса неудачных попыток до блокировки соединения (в секундах)",
        examples=[60, 3600],
    )

    # Безопасность
    ssl_verify: bool = Field(
        ...,
        title="Проверка SSL",
        description="Проверять сертификаты SSL",
        examples=[True],
    )

    # Параметры WAF
    # waf_url: str = Field(
    #     ...,
    #     description="URL для проверки безопасности",
    #     examples=["https://waf.example.com"],
    # )

    # waf_route_header: str = Field(
    #     ...,
    #     description="Заголовок, который содержит маршрут WAF",
    #     examples=["X-WAF-Route"],
    # )

    # Прочие
    ttl_dns_cache: int = Field(
        ...,
        title="TTL кэша DNS",
        ge=0,
        description="Время жизни кэша DNS-записей (в секундах)",
        examples=[3600],
    )

    @model_validator(mode="after")
    def validate_timeouts(self) -> "HttpBaseSettings":
        """Проверяет корректность настроек таймаутов."""
        if self.connect_timeout >= self.total_timeout:
            raise ValueError(
                "Таймаут подключения должен быть меньше общего таймаута"
            )
        return self


class SKBAPISettings(BaseSettingsWithLoader):
    """Настройки интеграции с API SKB-Tekhno."""

    yaml_group: ClassVar[str] = "skb"
    model_config = SettingsConfigDict(
        env_prefix="SKB_",
        extra="forbid",
    )

    # Аутентификация
    api_key: str = Field(
        ...,
        title="API-ключ",
        min_length=32,
        description="Секретный ключ для доступа к API",
        examples=["skb_1234567890abcdef"],
    )

    # URL
    prod_url: str = Field(
        ...,
        title="Продакшн URL",
        description="URL продакшн сервера",
        examples=["https://api.skb-tekhno.ru/v1"],
    )

    test_url: str = Field(
        ...,
        title="Тестовый URL",
        description="URL тестового сервера",
        examples=["https://test.skb-tekhno.ru/v1"],
    )

    endpoints: Dict[str, str] = Field(
        ...,
        description="API энпоинты'",
        examples=[{"users": "/users", "orders": "/orders"}],
    )

    # Параметры запросов
    default_priority: int = Field(
        ...,
        title="Приоритет по умолчанию",
        ge=1,
        le=100,
        description="Приоритет запросов от 1 (мин) до 100 (макс)",
        examples=[50],
    )

    # Таймауты
    connect_timeout: float = Field(
        ...,
        title="Таймаут подключения",
        ge=1.0,
        description="Максимальное время установки соединения",
        examples=[5.0],
    )

    read_timeout: float = Field(
        ...,
        description="Mаксимальное время чтения данных",
        examples=[30.0],
    )

    @model_validator(mode="after")
    def validate_urls(self) -> "SKBAPISettings":
        """Проверяет корректность URL."""
        if not self.prod_url.startswith("https"):
            raise ValueError("Продакшн URL должен использовать HTTPS")
        return self


class DadataAPISettings(BaseSettingsWithLoader):
    """Настройки интеграции с API Dadata."""

    yaml_group: ClassVar[str] = "dadata"
    model_config = SettingsConfigDict(
        env_prefix="DADATA_",
        extra="forbid",
    )

    # Аутентификация
    api_key: str = Field(
        ...,
        title="API-ключ",
        min_length=32,
        description="Секретный ключ для доступа к Dadata",
        examples=["dadata_0987654321abcdef"],
    )

    # URL
    base_url: str = Field(
        ...,
        description="API URL",
        examples=["https://suggestions.dadata.ru/suggestions/api/4_1/rs"],
    )

    endpoints: Dict[str, str] = Field(
        ...,
        description="API эндпоинты'",
        examples=[{"geolocate": "/geolocate", "suggest": "/suggest"}],
    )

    # Геолокация
    geolocate_radius_default: int = Field(
        ...,
        title="Радиус поиска",
        ge=100,
        le=10000,
        description="Радиус поиска по умолчанию в метрах",
        examples=[1000],
    )

    # Таймауты
    connect_timeout: float = Field(
        ...,
        title="Таймаут подключения",
        ge=1.0,
        description="Максимальное время установки соединения",
        examples=[5.0],
    )

    read_timeout: float = Field(
        ...,
        description="Mаксимальное время чтения данных",
        examples=[30.0],
    )


# Предварительно инициализированные конфигурации
http_base_settings = HttpBaseSettings()
"""Глобальные HTTP-настройки"""

skb_api_settings = SKBAPISettings()
"""Настройки интеграции с SKB-Tekhno"""

dadata_api_settings = DadataAPISettings()
"""Настройки интеграции с Dadata"""
