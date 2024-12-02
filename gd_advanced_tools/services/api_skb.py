import json
import re
import sys
import traceback
from uuid import UUID

import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.core.storage import s3_bucket_service_factory
from gd_advanced_tools.services.order_kinds import OrderKindService


__all__ = ("APISKBService",)


api_endpoints = settings.api_settings.skb_endpoint


class APISKBService:

    params = {"api-key": settings.api_settings.skb_api_key}
    endpoint = settings.api_settings.skb_url
    file_storage = s3_bucket_service_factory()

    async def get_request_kinds(self):
        async with httpx.AsyncClient() as client:
            response = client.get(
                f"{self.endpoint}{api_endpoints.get("Kinds")}", params=self.params
            )
            for el in response.json().get("Data"):
                await OrderKindService().get_or_add(
                    key="skb_uuid",
                    value=el.get("Id"),
                    data={"name": el.get("Name"), "skb_uuid": el.get("Id")},
                )
            return response.json().get("Data")

    async def add_request(self, data: dict) -> dict:
        try:
            async with httpx.AsyncClient() as client:
                response = client.post(
                    f"{self.endpoint}{api_endpoints.get("CREATE_REQUEST")}",
                    params=self.params,
                    data=data,
                )
                if response.status_code != 200:
                    raise ValueError(
                        f"Request failed with status code: {response.status_code}"
                    )
                return response.json()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return {"error": str(ex)}

    async def get_response_by_order(
        self, order_uuid: UUID, response_type: str | None
    ) -> dict:
        try:
            self.params["Type"] = response_type if response_type else None
            url = f"{self.endpoint}{api_endpoints.get("GET_RESULT")}/{str(order_uuid)}"
            async with httpx.AsyncClient() as client:
                response = client.get(url, params=self.params)

                if response.status_code != 200:
                    raise ValueError(
                        f"Request failed with status code: {response.status_code}"
                    )

                content_encoding = response.headers.get("Content-Encoding", "").lower()
                if "gzip" in content_encoding:
                    response.raw.decode_content = True

                if response_type == "JSON":
                    return json.loads(response.text)
                else:
                    filename = f"{str(order_uuid)}"
                    content = await response.aread()
                    content_disposition = response.headers.get("Content-Disposition")
                    if content_disposition:
                        filename_match = re.search(
                            r"filename=([^;]+)", content_disposition
                        )
                        if filename_match:
                            filename = filename_match.group(1).strip('"')
                    return await self.file_storage.upload_file_object(
                        key=str(order_uuid), original_filename=filename, content=content
                    )
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return {"error": str(ex)}
