import re
from typing import Any, Dict, Optional
from uuid import UUID

import aiohttp
import asyncio
from fastapi import status
from fastapi.responses import JSONResponse
from urllib.parse import urljoin

from backend.core.http_client import make_request
from backend.core.settings import settings
from backend.core.storage import s3_bucket_service_factory
from backend.orderkinds.service import OrderKindService


__all__ = ("APISKBService",)


api_endpoints = settings.api_skb_settings.skb_endpoint


class APISKBService:
    """
    Сервис для взаимодействия с API СКБ-Техно.

    Предоставляет методы для получения справочника видов запросов, создания запросов
    и получения результатов по залогам.
    """

    params = {"api-key": settings.api_skb_settings.skb_api_key}
    endpoint = settings.api_skb_settings.skb_url
    file_storage = s3_bucket_service_factory()

    @staticmethod
    async def get_request_kinds() -> Dict[str, Any]:
        """
        Получить справочник видов запросов из СКБ-Техно.

        Returns:
            Dict[str, Any]: Справочник видов запросов или JSONResponse с ошибкой.
        """
        try:
            url = f"{urljoin(APISKBService.endpoint, api_endpoints.get('GET_KINDS'))}"
            response = await make_request("GET", url, params=APISKBService.params)
            result = await response.json()

            # Обработка и сохранение данных в OrderKindService
            tasks = [
                OrderKindService().get_or_add(
                    key="skb_uuid",
                    value=el.get("Id"),
                    data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                )
                for el in result.get("Data", [])
            ]
            await asyncio.gather(*tasks)

            return result
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @staticmethod
    async def add_request(data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Создать запрос на получение данных по залогу в СКБ-Техно.

        Args:
            data (Dict[str, Any]): Данные для создания запроса.

        Returns:
            Dict[str, Any]: Результат запроса или JSONResponse с ошибкой.
        """
        try:
            url = f"{urljoin(APISKBService.endpoint, api_endpoints.get('CREATE_REQUEST'))}"
            return await make_request(
                "POST", url, params=APISKBService.params, json=data
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @staticmethod
    async def get_response_by_order(
        order_uuid: UUID, response_type: Optional[str] = None
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
            params = {**APISKBService.params, "Type": response_type}
            url = f"{urljoin(APISKBService.endpoint, api_endpoints.get('GET_RESULT'))}/{order_uuid}"
            response = await make_request("GET", url, params=params)

            content_encoding = response.headers.get("Content-Encoding", "").lower()
            content_type = response.headers.get("Content-Type", "")

            if "gzip" in content_encoding:
                response.content._decoder = aiohttp.gunzip.GzipDeflateDecoder()

            if (
                response_type == "PDF"
                and "application/json" not in content_type.lower()
            ):
                filename = f"{order_uuid}"
                content = await response.read()

                content_disposition = response.headers.get("Content-Disposition")
                if content_disposition:
                    match = re.search(r'filename="?([^";]+)"?', content_disposition)
                    if match:
                        filename = match.group(1)

                return await APISKBService.file_storage.upload_file_object(
                    key=str(order_uuid),
                    original_filename=filename,
                    content=content,
                )

            return await response.json()
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком
