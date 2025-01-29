from typing import Dict

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

from app.config.constants import ROOT_DIR


__all__ = (
    "APISSKBSettings",
    "APIDADATASettings",
)

# Загрузка переменных окружения из файла .env
load_dotenv(ROOT_DIR / ".env")


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
