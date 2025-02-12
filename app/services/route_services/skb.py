from typing import Any, Dict, Optional
from urllib.parse import urljoin
from uuid import UUID

from app.config.settings import SKBAPISettings, settings
from app.services.infra_services.http import get_http_client


__all__ = (
    "APISKBService",
    "get_skb_service",
)


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
        self.base_url = self.settings.base_url
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

            if settings.http_base_settings.waf_url:
                url = settings.http_base_settings.waf_url
                headers = settings.http_base_settings.waf_route_header
            else:
                url = f"{urljoin(self.base_url, self.endpoints.get('GET_KINDS'))}"

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
        self, order_uuid: UUID, response_type: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Получить результат по залогу из СКБ-Техно.

        Args:
            order_uuid (UUID): UUID запроса.
            response_type (Optional[str]): Тип ответа (JSON или PDF).

        Returns:
            Dict[str, Any]: Результат запроса или информация об ошибке.
        """
        try:
            params = {**self.params, "Type": response_type}
            url = f"{urljoin(self.base_url, self.endpoints.get('GET_RESULT'))}/{order_uuid}"

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
