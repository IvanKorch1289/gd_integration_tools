"""S168 W17 P2-10: route_schemas для DaData.

S168 W17 P2-10: moved from src/backend/schemas/route_schemas/dadata.py
to extensions/dadata/schemas/route.py per master prompt v8 P2-10.
DaData is cross-cutting (external geolocation API) — own extension.
"""

from pydantic import Field

from src.backend.schemas.base import BaseSchema

__all__ = ("DadataGeolocateQuerySchema",)


class DadataGeolocateQuerySchema(BaseSchema):
    """
    Схема query-параметров для получения геолокации по координатам через DaData.

    Внешний контракт оставлен совместимым с текущим endpoint-ом:
    метод POST, параметры передаются через query string.

    Attributes:
        lat: Широта.
        lon: Долгота.
        count_results: Количество результатов в ответе.
        radius_metres: Радиус поиска в метрах.
    """

    lat: float = Field(description="Широта.")
    lon: float = Field(description="Долгота.")
    count_results: int | None = Field(
        default=10, ge=1, le=50, description="Количество результатов в ответе."
    )
    radius_metres: int | None = Field(
        default=500, ge=1, description="Радиус поиска в метрах."
    )
