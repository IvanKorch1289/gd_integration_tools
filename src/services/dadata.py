from typing import Any, Dict
from urllib.parse import urljoin

from app.core.config.settings import DadataAPISettings, settings
from app.core.decorators.caching import response_cache
from app.core.decorators.singleton import singleton
from app.core.errors import ServiceError
from app.infrastructure.clients.http import get_http_client_dependency

__all__ = ("APIDADATAService", "get_dadata_service")


@singleton
class APIDADATAService:
    """Сервис для работы с API Dadata."""

    def __init__(self, dadata_settings: DadataAPISettings) -> None:
        self.settings = dadata_settings
        self._initialize_attributes()

    def _initialize_attributes(self) -> None:
        self.auth_token = f"Token {self.settings.api_key}"
        self.base_url = self.settings.base_url
        self.endpoints = self.settings.endpoints

    @response_cache
    async def get_geolocate(
        self,
        lat: float,
        lon: float,
        count_results: int | None = None,
        radius_metres: int | None = None,
    ) -> Dict[str, Any] | None:
        """Получает адрес по координатам через API Dadata."""
        payload: Dict[str, Any] = {"lat": lat, "lon": lon}

        if radius_metres is not None:
            payload["radius_meters"] = radius_metres
        if count_results is not None:
            payload["count"] = count_results

        headers = {}
        if settings.http_base_settings.waf_url:
            url = settings.http_base_settings.waf_url
            headers.update(settings.http_base_settings.waf_route_header)
        else:
            endpoint = self.endpoints.get("GEOLOCATE") or "geolocate/address"
            url = urljoin(self.base_url, endpoint)

        try:
            # Используем get_http_client_dependency для singleton инстанса
            client = get_http_client_dependency()
            return await client.make_request(
                method="POST",
                url=url,
                json=payload,
                auth_token=self.auth_token,
                headers=headers,
                response_type="json",
                raise_for_status=False,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
            )
        except Exception as exc:
            raise ServiceError from exc


def get_dadata_service() -> APIDADATAService:
    return APIDADATAService(dadata_settings=settings.dadata_api)
