from typing import Any, Dict

from fastapi import APIRouter, Header
from fastapi_utils.cbv import cbv

from app.services.route_services.dadata import get_dadata_service


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class DADATACBV:
    """
    Класс для обработки запросов, связанных с API Dadata.

    Использует класс APIDADATAService для взаимодействия с API Dadata.

    Attributes:
        service (APIDADATAService): Сервис для работы с API Dadata.
    """

    service = get_dadata_service()

    @router.post(
        "/get-geolocate",
        summary="Получить геолокацию по координатам",
        description="Получает информацию о геолокации по переданным координатам (широта и долгота). "
        "Можно указать радиус поиска в метрах.",
        response_model=None,
    )
    async def get_geolocate_by_coordinates(
        self,
        lat: float,
        lon: float,
        count_results: int | None = 10,
        radius_metres: int | None = 500,
        x_api_key: str = Header(...),
    ) -> Dict[str, Any]:
        """
        Получает информацию о геолокации по координатам.

        Args:
            lat (float): Широта.
            lon (float): Долгота.
            radius_metres (int | None): Радиус поиска в метрах (опционально).
            x_api_key (str): API-ключ для авторизации (передается в заголовке).

        Returns:
            Dict[str, Any]: Ответ от API Dadata с информацией о геолокации.
        """
        return await self.service.get_geolocate(
            lat=lat,
            lon=lon,
            count_results=count_results,
            radius_metres=radius_metres,
        )
