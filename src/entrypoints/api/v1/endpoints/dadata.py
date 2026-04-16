from fastapi import APIRouter, Depends

from app.entrypoints.api.dependencies.auth import require_api_key
from app.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from app.schemas.route_schemas.dadata import DadataGeolocateQuerySchema
from app.services.dadata import get_dadata_service

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)

builder.add_actions(
    [
        ActionSpec(
            name="get_geolocate_by_coordinates",
            method="POST",
            path="/get-geolocate",
            summary="Получить геолокацию по координатам",
            description=(
                "Получает информацию о геолокации по переданным координатам "
                "(широта и долгота). Можно указать радиус поиска в метрах."
            ),
            service_getter=get_dadata_service,
            service_method="get_geolocate",
            query_model=DadataGeolocateQuerySchema,
            response_model=None,
            dependencies=[Depends(require_api_key)],
            tags=("DaData",),
        )
    ]
)
