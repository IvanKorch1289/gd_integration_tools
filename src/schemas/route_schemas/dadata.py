from pydantic import Field

from src.schemas.base import BaseSchema

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
