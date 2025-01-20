from fastapi import APIRouter, Header
from fastapi_utils.cbv import cbv

from backend.dadata.service import APIDADATAService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class DADATACBV:

    service = APIDADATAService

    @router.post("/get-geolocate", summary="Получить геолокацию по коррдинатам")
    async def get_geolocate_by_coordinates(
        self,
        lat: float,
        lon: float,
        radius_metres: int | None = None,
        x_api_key: str = Header(...),
    ):
        return await self.service.get_geolocate(
            lat=lat, lon=lon, radius_metres=radius_metres
        )
