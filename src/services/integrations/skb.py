from typing import Any
from urllib.parse import urljoin
from uuid import UUID

from app.core.config.settings import SKBAPISettings, settings
from app.core.errors import ServiceError
from app.infrastructure.clients.transport.http import get_http_client_dependency

__all__ = ("APISKBService", "get_skb_service")


class APISKBService:
    """Сервис для взаимодействия с API СКБ-Техно."""

    def __init__(self, skb_settings: SKBAPISettings) -> None:
        self.settings = skb_settings
        self._initialize_attributes()

    def _initialize_attributes(self) -> None:
        self.params = {"api-key": self.settings.api_key}
        self.base_url = self.settings.prod_url
        self.endpoints = self.settings.endpoints
        self.client = get_http_client_dependency()

    def _get_url(self, endpoint_key: str) -> str:
        """Вспомогательный метод для формирования URL"""
        endpoint = self.endpoints.get(endpoint_key, "")
        return urljoin(self.base_url, endpoint)

    async def get_request_kinds(self) -> dict[str, Any]:
        """Получить справочник видов запросов из СКБ-Техно."""
        try:
            url = None
            headers = {}

            if (
                settings.app.environment == "production"
                and settings.http_base_settings.waf_url
            ):
                url = settings.http_base_settings.waf_url
                headers = settings.http_base_settings.waf_route_header
            else:
                url = self._get_url("GET_KINDS")

            return await self.client.make_request(
                method="GET",
                url=url,
                params=self.params,
                headers=headers,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
            )
        except Exception as exc:
            raise ServiceError from exc

    async def add_request(self, data: dict[str, Any]) -> dict[str, Any]:
        """Создать запрос на получение данных по залогу в СКБ-Техно."""
        try:
            url = self._get_url("CREATE_REQUEST")

            return await self.client.make_request(
                method="POST",
                url=url,
                params=self.params,
                json=data,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_response_by_order(
        self, order_uuid: UUID, response_type_str: str | None = None
    ) -> Any | dict[str, Any]:
        """Получить результат по залогу из СКБ-Техно."""
        try:
            params = {**self.params, "Type": response_type_str}
            # urljoin не очень дружит с добавлением path params, если в конце нет слеша
            base_endpoint = self._get_url("GET_RESULT")
            url = f"{base_endpoint.rstrip('/')}/{order_uuid}"

            response = await self.client.make_request(
                method="GET",
                url=url,
                params=params,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
                response_type=("bytes" if response_type_str == "PDF" else "json"),
                raise_for_status=False,
            )

            return response.get("data") if response_type_str == "PDF" else response
        except Exception as exc:
            raise ServiceError from exc

    async def get_orders_list(
        self, take: int | None = None, skip: int | None = None
    ) -> dict[str, Any]:
        """Получить список заказов документов по залогу из СКБ-Техно."""
        try:
            params = {**self.params}
            if take is not None:
                params["take"] = take
            if skip is not None:
                params["skip"] = skip

            url = self._get_url("GET_ORDER_LIST")

            return await self.client.make_request(
                method="GET",
                url=url,
                params=params,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
                raise_for_status=False,
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_objects_by_address(
        self, query: str, comment: str | None = None
    ) -> dict[str, Any]:
        """Проверка-поиск объектов недвижимости по адресу."""
        try:
            params: dict[str, Any] = {**self.params, "query": query}
            if comment is not None:
                params["comment"] = comment

            url = self._get_url("CHECK_ADDRESS")

            return await self.client.make_request(
                method="POST",
                url=url,
                params=params,
                connect_timeout=self.settings.connect_timeout,
                read_timeout=self.settings.read_timeout,
                total_timeout=self.settings.connect_timeout
                + self.settings.read_timeout,
                raise_for_status=False,
            )
        except Exception as exc:
            raise ServiceError from exc


_skb_service_instance: APISKBService | None = None


def get_skb_service() -> APISKBService:
    global _skb_service_instance
    if _skb_service_instance is None:
        _skb_service_instance = APISKBService(skb_settings=settings.skb_api)
    return _skb_service_instance
