"""DaData API сервис — геокодирование адресов поверх ``BaseExternalAPIClient``."""

from typing import Any
from urllib.parse import urljoin

from src.core.config.settings import DadataAPISettings, settings
from src.core.errors import ServiceError
from src.infrastructure.decorators.caching import response_cache
from src.services.core.base_external_api import BaseExternalAPIClient

__all__ = ("APIDADATAService", "get_dadata_service")


class APIDADATAService(BaseExternalAPIClient):
    """Сервис для работы с API Dadata (схема Authorization: ``Token <key>``)."""

    _auth_scheme = "Token"

    def __init__(self, dadata_settings: DadataAPISettings) -> None:
        super().__init__(settings=dadata_settings, name="dadata")

    @response_cache
    async def get_geolocate(
        self,
        lat: float,
        lon: float,
        count_results: int | None = None,
        radius_metres: int | None = None,
    ) -> dict[str, Any] | None:
        """Получает адрес по координатам через API Dadata."""
        payload: dict[str, Any] = {"lat": lat, "lon": lon}
        if radius_metres is not None:
            payload["radius_meters"] = radius_metres
        if count_results is not None:
            payload["count"] = count_results

        waf_url = settings.http_base_settings.waf_url
        if waf_url:
            url = waf_url
            use_waf = True
        else:
            url = self._url("GEOLOCATE") or urljoin(self.base_url, "geolocate/address")
            use_waf = False

        try:
            return await self._request(
                "POST",
                url,
                json=payload,
                use_waf=use_waf,
                response_type="json",
                raise_for_status=False,
            )
        except Exception as exc:
            raise ServiceError from exc


_dadata_service_instance: APIDADATAService | None = None


def get_dadata_service() -> APIDADATAService:
    global _dadata_service_instance
    if _dadata_service_instance is None:
        _dadata_service_instance = APIDADATAService(dadata_settings=settings.dadata_api)
    return _dadata_service_instance
