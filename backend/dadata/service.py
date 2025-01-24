from typing import Any, Dict, Optional

from backend.core.http_client import make_request
from backend.core.redis import caching_decorator
from backend.core.settings import settings


__all__ = ("APIDADATAService",)


API_ENDPOINTS = settings.dadata_settings.dadata_endpoint


class APIDADATAService:
    """Сервис для работы с API Dadata.

    Предоставляет методы для взаимодействия с API Dadata, такие как геокодирование.

    Attributes:
        auth_token (str): Токен для авторизации в API Dadata.
        endpoint (str): Базовый URL API Dadata.
    """

    auth_token = f"Token {settings.dadata_settings.dadata_api_key}"
    endpoint = settings.dadata_settings.dadata_url

    @classmethod
    @caching_decorator
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

        # Формируем URL для запроса
        url = f"{cls.endpoint}{API_ENDPOINTS.get('GEOLOCATE')}"

        # Выполняем запрос с помощью универсального метода make_request
        return await make_request(
            method="POST",
            url=url,
            json=payload,
            auth_token=cls.auth_token,
            response_type="json",
        )


# Функция-зависимость для создания экземпляра APIDADATAService
def get_dadata_service() -> APIDADATAService:
    """
    Возвращает экземпляр APIDADATAService.

    Returns:
        APIDADATAService: Экземпляр сервиса для работы с API Dadata.
    """
    return APIDADATAService()
