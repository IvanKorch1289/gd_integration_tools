import re
from typing import Any, Dict, Optional, Type
from uuid import UUID

import aiohttp
import asyncio
from urllib.parse import urljoin

from app.config.settings import SKBAPISettings, settings
from app.infra.storage import s3_bucket_service_factory
from app.services.helpers.http_helper import get_http_client
from app.services.route_services.base import BaseService
from app.services.route_services.orderkinds import get_order_kind_service


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

    def __init__(
        self, settings: SKBAPISettings, kind_service: Type[BaseService] = None
    ):
        self.kind_service = kind_service
        self.settings = settings
        self.file_storage = s3_bucket_service_factory()
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
            url = f"{urljoin(self.base_url, self.endpoints.get('GET_KINDS'))}"

            async with get_http_client() as client:
                result = await client.make_request(
                    method="GET",
                    url=url,
                    params=self.params,
                    connect_timeout=self.settings.connect_timeout,
                    read_timeout=self.settings.read_timeout,
                    total_timeout=self.settings.connect_timeout
                    + self.settings.read_timeout,
                )

            # Обработка и сохранение данных в OrderKindService
            tasks = [
                self.kind_service.get_or_add(
                    key="skb_uuid",
                    value=el.get("Id"),
                    data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                )
                for el in result.get("data", []).get("Data", None)
            ]
            await asyncio.gather(*tasks)

            return result
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
            url = f"{urljoin(self.base_url, self.endpoints.get('CREATE_REQUEST'))}"

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
                )

            content_encoding = response.headers.get(
                "Content-Encoding", ""
            ).lower()
            content_type = response.headers.get("Content-Type", "")

            if "gzip" in content_encoding:
                response.content._decoder = aiohttp.gunzip.GzipDeflateDecoder()

            if (
                response_type == "PDF"
                and "application/json" not in content_type.lower()
            ):
                filename = f"{order_uuid}"
                content = await response.read()

                content_disposition = response.headers.get(
                    "Content-Disposition"
                )
                if content_disposition:
                    match = re.search(
                        r'filename="?([^";]+)"?', content_disposition
                    )
                    if match:
                        filename = match.group(1)

                return await self.file_storage.upload_file_object(
                    key=str(order_uuid),
                    original_filename=filename,
                    content=content,
                )

            return await response.json()
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
    return APISKBService(
        settings=settings.skb_api, kind_service=get_order_kind_service()
    )
