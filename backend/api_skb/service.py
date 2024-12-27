import re
import sys
import traceback
from uuid import UUID

import aiohttp
import asyncio
from aiohttp import ClientSession
from fastapi import status
from fastapi.responses import JSONResponse
from urllib.parse import urljoin

from backend.core.settings import settings
from backend.core.storage import s3_bucket_service_factory
from backend.core.utils import utilities
from backend.order_kinds.service import OrderKindService


__all__ = ("APISKBService",)


api_endpoints = settings.api_skb_settings.skb_endpoint


class APISKBService:

    params = {"api-key": settings.api_skb_settings.skb_api_key}
    endpoint = settings.api_skb_settings.skb_url
    file_storage = s3_bucket_service_factory()

    @utilities.caching(expire=300)
    async def get_request_kinds(self):
        async with ClientSession() as session:
            try:
                url = f"{urljoin(self.endpoint, api_endpoints.get("GET_KINDS"))}"
                async with session.get(url=url, params=self.params) as response:
                    response.raise_for_status()
                    result = await response.json()
                    tasks = []
                    for el in result.get("Data", []):
                        task = OrderKindService().get_or_add(
                            key="skb_uuid",
                            value=el.get("Id"),
                            data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                        )
                        tasks.append(task)
                    await asyncio.gather(*tasks)
                    return result
            except Exception:
                traceback.print_exc(file=sys.stdout)
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "hasError": True,
                        "message": "Failed to execute the query",
                    },
                )

    async def add_request(self, data: dict) -> dict:
        async with ClientSession() as session:
            try:
                url = f"{urljoin(self.endpoint, api_endpoints.get("CREATE_REQUEST"))}"
                async with session.post(
                    url=url, params=self.params, data=data
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    if response.status != status.HTTP_200_OK:
                        message = {
                            "orderInfo": result,
                            "hasError": True,
                            "message": f"Request failed with status code: {response.status}",
                        }
                        return JSONResponse(
                            status_code=response.status, content=message
                        )
                    return JSONResponse(status_code=status.HTTP_200_OK, content=result)
            except Exception:
                traceback.print_exc(file=sys.stdout)
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "hasError": True,
                        "message": "Failed to execute the query",
                    },
                )

    @utilities.caching(expire=300)
    async def get_response_by_order(
        self, order_uuid: UUID, response_type: str | None
    ) -> dict:
        """Получает ответ по заказу и возвращает данные в зависимости от типа ответа."""
        async with ClientSession() as session:
            try:
                self.params["Type"] = response_type
                url = f"{urljoin(self.endpoint, api_endpoints.get('GET_RESULT'))}/{order_uuid}"
                async with session.get(url, params=self.params) as response:
                    response.raise_for_status()

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
                    result = await response.json()
                    return JSONResponse(
                        status_code=(
                            response.status
                            if response.status >= 300
                            else status.HTTP_200_OK
                        ),
                        content=result,
                    )
            except Exception:
                traceback.print_exc(file=sys.stderr)
                return JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={
                        "hasError": True,
                        "message": "Failed to execute the query",
                    },
                )
