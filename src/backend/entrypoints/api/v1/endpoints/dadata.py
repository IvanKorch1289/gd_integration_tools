"""DaData endpoints — проксирование запросов к DaData.ru API.

Routes registered:
* ``GET /api/v1/dadata/suggest`` — autocomplete по адресу/ФИО/email;
* ``GET /api/v1/dadata/find_by_id`` — поиск по ИНН/ОГРН.

Используется :mod:`extensions.dadata.services.dadata` для обращения к API.
"""

from fastapi import APIRouter, Depends

from src.backend.core.extension_registry import get_extension_resource
from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.services.integrations.dadata import get_dadata_service

__all__ = ("router",)


# ADR-0457: объект расширения получается через core-реестр (инверсия
# зависимости ``src/ → extensions``), а не прямым импортом ``extensions.*``.
# Резолв на уровне модуля — FastAPI строит модель при импорте.
DadataGeolocateQuerySchema = get_extension_resource("dadata", "schema", "geolocate")


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
