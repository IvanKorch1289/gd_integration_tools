from typing import Any, Dict, Optional

from urllib.parse import urljoin

from app.config.settings import DadataAPISettings, settings
from app.services.infra_services.http import get_http_client
from app.utils.decorators.caching import response_cache


__all__ = (
    "APIDADATAService",
    "get_dadata_service",
)


class APIDADATAService:
    """Сервис для работы с API Dadata.

    Предоставляет методы для взаимодействия с API Dadata, такие как геокодирование.

    Attributes:
        auth_token (str): Токен для авторизации в API Dadata.
        endpoint (str): Базовый URL API Dadata.
    """

    def __init__(self, settings):
        """
        Инициализация клиента с настройками API

        Args:
            settings: Объект с параметрами API
        """
        self.settings: DadataAPISettings = settings
        self._initialize_attributes()

    def _initialize_attributes(self):
        """Инициализирует атрибуты из настроек"""
        self.auth_token = f"Token {self.settings.api_key}"
        self.base_url = self.settings.base_url
        self.endpoints = self.settings.endpoints

    @classmethod
    @response_cache
    async def get_geolocate(
        cls,
        lat: float,
        lon: float,
        radius_metres: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Получает адрес по координатам (широта и долгота) через API Dadata.

        Args:
            lat (float): Широта.
            lon (float): Долгота.
            radius_metres (Optional[int]): Радиус поиска в метрах (максимум – 1000).

        Returns:
            Optional[Dict[str, Any]]: Ответ от API Dadata в формате JSON или None в случае ошибки.
        """
        # Формируем тело запроса
        payload = {"lat": lat, "lon": lon}
        if radius_metres:
            payload["radius_meters"] = radius_metres

        url = None
        headers = {}

        # Формируем URL для запроса
        if settings.http_base_settings.waf_url:
            url = settings.http_base_settings.waf_url
            headers = settings.http_base_settings.waf_route_header
        else:
            url = f"{urljoin(cls.base_url, cls.endpoints.get('GEOLOCATE'))}"

        # Выполняем запрос с помощью универсального метода make_request
        async with get_http_client() as client:
            return await client.make_request(
                method="POST",
                url=url,
                json=payload,
                auth_token=cls.auth_token,
                headers=headers,
                response_type="json",
                connect_timeout=cls.settings.connect_timeout,
                read_timeout=cls.settings.read_timeout,
                total_timeout=cls.settings.connect_timeout
                + cls.settings.read_timeout,
            )


# Функция-зависимость для создания экземпляра APIDADATAService
def get_dadata_service() -> APIDADATAService:
    """
    Возвращает экземпляр APIDADATAService.

    Returns:
        APIDADATAService: Экземпляр сервиса для работы с API Dadata.
    """
    return APIDADATAService(settings=settings.dadata_api)
