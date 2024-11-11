import sys
import traceback
from uuid import uuid4

import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.schemas import ApiOrderSchemaIn, OrderKindSchemaIn
from gd_advanced_tools.services.order_kinds import OrderKindService


__all__ = ('APISKBService', )


class APISKBService:

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
        schema: ApiOrderSchemaIn
    ) -> dict:
        try:
            request = httpx.post(
                self.endpoint+'Create',
                params=self.params,
                data=schema.model_dump()
            )
            return request.json()
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex
