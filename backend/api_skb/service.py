import re
import sys
import traceback
from uuid import UUID

import aiohttp
import asyncio
from fastapi import status
from fastapi.responses import JSONResponse
from urllib.parse import urljoin

from backend.core.http_client import LoggingClientSession
from backend.core.settings import settings
from backend.core.storage import s3_bucket_service_factory
from backend.order_kinds.service import OrderKindService


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

    async def _make_request(
        self, method: str, url: str, **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Универсальный метод для выполнения HTTP-запросов.

        Args:
            method (str): HTTP-метод (GET, POST и т.д.).
            url (str): URL запроса.
            **kwargs: Дополнительные аргументы для запроса.

        Returns:
            aiohttp.ClientResponse: Ответ от сервера.
        """
        async with LoggingClientSession() as session:
            try:
                response = await session.request(method, url, **kwargs)
                response.raise_for_status()
                return response
            except Exception as e:
                traceback.print_exc(file=sys.stdout)
                raise e

    async def get_request_kinds(self):
        """
        Получить справочник видов запросов из СКБ-Техно.

        :return: Справочник видов запросов или JSONResponse с ошибкой.
        """
        try:
            url = f"{urljoin(self.endpoint, api_endpoints.get('GET_KINDS'))}"
            response = await self._make_request("GET", url, params=self.params)
            result = await response.json()
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
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "hasError": True,
                    "message": "Failed to execute the query",
                },
            )

    async def add_request(self, data: dict) -> dict:
        """
        Создать запрос на получение данных по залогу в СКБ-Техно.

        :param data: Данные для создания запроса.
        :return: Результат запроса или JSONResponse с ошибкой.
        """
        try:
            url = f"{urljoin(self.endpoint, api_endpoints.get('CREATE_REQUEST'))}"
            response = await self._make_request(
                "POST", url, params=self.params, data=data
            )
            result = await response.json()
            if response.status != status.HTTP_200_OK:
                message = {
                    "orderInfo": result,
                    "hasError": True,
                    "message": f"Request failed with status code: {response.status}",
                }
                return JSONResponse(status_code=response.status, content=message)
            return JSONResponse(status_code=status.HTTP_200_OK, content=result)
        except Exception:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={
                    "hasError": True,
                    "message": "Failed to execute the query",
                },
            )

    async def get_response_by_order(
        self, order_uuid: UUID, response_type: str | None
    ) -> dict:
        """
        Получить результат по залогу из СКБ-Техно.

        :param order_uuid: UUID запроса.
        :param response_type: Тип ответа (JSON или PDF).
        :return: Результат запроса или JSONResponse с ошибкой.
        """
        try:
            self.params["Type"] = response_type
            url = f"{urljoin(self.endpoint, api_endpoints.get('GET_RESULT'))}/{order_uuid}"
            response = await self._make_request("GET", url, params=self.params)

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

                return await self.file_storage.upload_file_object(
                    key=str(order_uuid),
                    original_filename=filename,
                    content=content,
                )

            # Используем response.json() для автоматического преобразования в JSON
            result = await response.json()
            return {
                "data": result,  # Возвращаем только данные, без заголовков
                "from_cache": False,
                "ttl": 300,
                "error": None,
            }
        except Exception as e:
            traceback.print_exc(file=sys.stderr)
            return {"data": None, "from_cache": False, "ttl": 0, "error": str(e)}
