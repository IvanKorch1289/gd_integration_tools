from typing import Any, Dict, Optional
from urllib.parse import urljoin
from uuid import UUID

from app.config.settings import SKBAPISettings, settings
from app.services.infra_services.http import get_http_client
from app.utils.decorators.singleton import singleton


__all__ = (
    "APISKBService",
    "get_skb_service",
)


@singleton
class APISKBService:
    """
    Сервис для взаимодействия с API СКБ-Техно.

    Предоставляет методы для получения справочника видов запросов, создания запросов
    и получения результатов по залогам.
    """

    def __init__(self, settings: SKBAPISettings):
        self.settings = settings
        self._initialize_attributes()

    def _initialize_attributes(self):
        """Инициализирует атрибуты из настроек"""
        self.params = {"api-key": self.settings.api_key}
        # self.base_url = (
        #     self.settings.prod_url
        #     if settings.app.environment == "production"
        #     else self.settings.test_url
        # )
        self.base_url = self.settings.prod_url
        self.endpoints = self.settings.endpoints

    async def get_request_kinds(self) -> Dict[str, Any]:
        """
        Получить справочник видов запросов из СКБ-Техно.

        Returns:
            Dict[str, Any]: Справочник видов запросов или JSONResponse с ошибкой.
        """
        try:
            url = None
            headers = {}

            if settings.app.environment == "production":
                url = settings.http_base_settings.waf_url
                headers = settings.http_base_settings.waf_route_header
            else:
                url = f"{urljoin(self.base_url, self.endpoints.get("GET_KINDS"))}"

            async with get_http_client() as client:
                return await client.make_request(
                    method="GET",
                    url=url,
                    params=self.params,
                    headers=headers,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def add_request(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создать запрос на получение данных по залогу в СКБ-Техно.

        Args:
            data (Dict[str, Any]): Данные для создания запроса.

        Returns:
            Dict[str, Any]: Результат запроса или JSONResponse с ошибкой.
        """
        try:
            url = f"{urljoin(self.base_url, self.endpoints.get("CREATE_REQUEST"))}"

            async with get_http_client() as client:
                return await client.make_request(
                    method="POST",
                    url=url,
                    params=self.params,
                    json=data,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_response_by_order(
        self, order_uuid: UUID, response_type_str: Optional[str] = None
    ) -> Any | Dict[str, Any]:
        """
        Получить результат по залогу из СКБ-Техно.

        Args:
            order_uuid (UUID): UUID запроса.
            response_type (Optional[str]): Тип ответа (JSON или PDF).

        Returns:
            Dict[str, Any]: Результат запроса или информация об ошибке.
        """
        try:
            params = {**self.params, "Type": response_type_str}
            url = f"{urljoin(self.base_url, self.endpoints.get("GET_RESULT"))}/{order_uuid}"

            async with get_http_client() as client:
                response = await client.make_request(
                    method="GET",
                    url=url,
                    params=params,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                    response_type=(
                        "bytes" if response_type_str == "PDF" else "json"
                    ),
                    raise_for_status=False,
                )

                return (
                    response.get("data")
                    if response_type_str == "PDF"
                    else response
                )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_orders_list(
        self,
        take: int = None,
        skip: int = None,
    ) -> Dict[str, Any]:
        """
        Получить список заказов документов по залогу из СКБ-Техно.

        Args:
            take (Optional[int]): Количество запросов, которые нужно выбрать.
            skip (Optional[int]): Количетсво запросов, которые нужно пропустить.

        Returns:
            Dict[str, Any]: Результат запроса или информация об ошибке.
        """
        try:
            params = {**self.params}
            if take is not None:
                params["take"] = take

            if skip is not None:
                params["skip"] = skip

            url = f"{urljoin(self.base_url, self.endpoints.get("GET_ORDER_LIST"))}"

            async with get_http_client() as client:
                response = await client.make_request(
                    method="GET",
                    url=url,
                    params=params,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                    raise_for_status=False,
                )

                return response
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_objects_by_address(
        self,
        query: str,
        comment: str = None,
    ) -> Dict[str, Any]:
        """
        Проверка-поиск объектов недвижимости по адресу (ФИАС/КЛАДР)..

        Args:
            query (str): Адрес.
            comment (Optional[str]): Комментарий.

        Returns:
            Dict[str, Any]: Результат запроса или информация об ошибке.
        """
        try:
            params = {**self.params, "query": query}
            if comment is not None:
                params["comment"] = comment

            url = f"{urljoin(self.base_url, self.endpoints.get("CHECK_ADDRESS"))}"

            async with get_http_client() as client:
                response = await client.make_request(
                    method="POST",
                    url=url,
                    params=params,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                    raise_for_status=False,
                )

                return response
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком


# Функция-зависимость для создания экземпляра APISKBService
def get_skb_service() -> APISKBService:
    """
    Возвращает экземпляр APISKBService с внедренной зависимостью OrderKindService.

    Args:
        kind_service (OrderKindService): Сервис для работы с видами запросов.

    Returns:
        APISKBService: Экземпляр APISKBService.
    """
    return APISKBService(settings=settings.skb_api)
