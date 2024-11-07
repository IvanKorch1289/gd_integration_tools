from typing import Optional
from uuid import uuid4

import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.models import Order
from gd_advanced_tools.schemas import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderKindSchemaIn
)
from gd_advanced_tools.services.order_kinds import OrderKindService


__all__ = ('APISKBKindService', )


class APISKBKindService:

    params = {'api-key': settings.api_settings.api_key}
    endpoint = settings.api_settings.skb_url

    async def get_request_kinds(self):
        request = httpx.get(self.endpoint+'Kinds', params=self.params)
        for el in request.json().get('Data'):
            data = {}
            data['name'] = el.get('Name')
            data['skb_uuid'] = el.get('Id')
            await OrderKindService().get_or_add(
                key='skb_uuid',
                value=el.get('Id'),
                schema=OrderKindSchemaIn(**data)
            )
        return request.json().get('Data')

    async def add_request(
        self,
        schema: OrderSchemaIn
    ) -> Optional[OrderSchemaOut]:
        try:
            req_number = uuid4()

            data = {}
            data['Id'] = req_number
            data['OrderId'] = req_number
            data['Number'] = ''
            data['Priority'] = 80
            data['RequestType'] = ''
            request = httpx.post(
                self.endpoint+'Create',
                params=self.params,
                data=data
            )
            return request.json()

        except Exception as ex:
            return ex
