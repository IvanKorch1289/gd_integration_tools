import sys
import traceback
from uuid import UUID

import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.schemas import OrderKindSchemaIn
from gd_advanced_tools.services.order_kinds import OrderKindService

__all__ = ("APISKBService",)


class APISKBService:

    params = {"api-key": settings.api_settings.skb_api_key}
    endpoint = settings.api_settings.skb_url

    async def get_request_kinds(self):
        request = httpx.get(self.endpoint + "Kinds", params=self.params)
        for el in request.json().get("Data"):
            data = {}
            data["name"] = el.get("Name")
            data["skb_uuid"] = el.get("Id")
            await OrderKindService().get_or_add(
                key="skb_uuid", value=el.get("Id"), data=data
            )
        return request.json().get("Data")

    async def add_request(self, data: dict) -> dict:
        try:
            request = httpx.post(
                self.endpoint + "Create", params=self.params, data=data
            )
            return request.json()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def get_response_by_order(
        self, order_uuid: UUID, response_type: str | None
    ) -> dict:
        try:
            self.params["Type"] = response_type if response_type else None
            request = httpx.get(
                self.endpoint + "Result/" + str(order_uuid),
                params=self.params,
            )
            return request.json()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
