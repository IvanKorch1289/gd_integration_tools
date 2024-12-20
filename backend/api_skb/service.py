import json
import re
import sys
import traceback
from uuid import UUID

import asyncio
from aiohttp import ClientSession
from fastapi import status

from backend.core.settings import settings
from backend.core.storage import s3_bucket_service_factory
from backend.order_kinds.service import OrderKindService


__all__ = ("APISKBService",)


api_endpoints = settings.api_settings.skb_endpoint


class APISKBService:

    params = {"api-key": settings.api_settings.skb_api_key}
    endpoint = settings.api_settings.skb_url
    file_storage = s3_bucket_service_factory()

    async def get_request_kinds(self):
        async with ClientSession() as session:
            try:
                async with session.get(
                    f"{self.endpoint}{api_endpoints.get("GET_KINDS")}",
                    params=self.params,
                ) as response:
                    response.raise_for_status()
                    json_data = await response.json()
            except Exception as exc:
                traceback.print_exc(file=sys.stdout)
                return exc
            else:
                tasks = []
                for el in json_data.get("Data", []):
                    task = OrderKindService().get_or_add(
                        key="skb_uuid",
                        value=el.get("Id"),
                        data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                    )
                    tasks.append(task)
                await asyncio.gather(*tasks)
                return json_data.get("Data")

    async def add_request(self, data: dict) -> dict:
        async with ClientSession() as session:
            try:
                async with session.post(
                    f"{self.endpoint}{api_endpoints.get("CREATE_REQUEST")}",
                    params=self.params,
                    data=data,
                ) as response:
                    if response.status != status.HTTP_200_OK:
                        raise ValueError(
                            f"Request failed with status code: {response.status}"
                        )
                    return await response.json()
            except Exception as ex:
                traceback.print_exc(file=sys.stdout)
                return {"error": str(ex)}

    async def get_response_by_order(
        self, order_uuid: UUID, response_type: str | None
    ) -> dict:
        async with ClientSession() as session:
            try:
                self.params["Type"] = response_type if response_type else None
                url = f"{self.endpoint}{api_endpoints.get("GET_RESULT")}/{str(order_uuid)}"
                async with session.get(url, params=self.params) as response:
                    if response.status != status.HTTP_200_OK:
                        return await response.json()
                    content_encoding = response.headers.get(
                        "Content-Encoding", ""
                    ).lower()
                    if "gzip" in content_encoding:
                        response.raw.decode_content = True

                    if response_type == "JSON":
                        return json.loads(response.text)
                    else:
                        filename = f"{str(order_uuid)}"
                        content = await response.aread()
                        content_disposition = response.headers.get(
                            "Content-Disposition"
                        )
                        if content_disposition:
                            filename_match = re.search(
                                r"filename=([^;]+)", content_disposition
                            )
                            if filename_match:
                                filename = filename_match.group(1).strip('"')
                        return await self.file_storage.upload_file_object(
                            key=str(order_uuid),
                            original_filename=filename,
                            content=content,
                        )
            except Exception as ex:
                traceback.print_exc(file=sys.stdout)
                return {"error": str(ex)}
