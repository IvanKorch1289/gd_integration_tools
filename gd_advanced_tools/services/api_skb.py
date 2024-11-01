from typing import Annotated
from fastapi import Depends
import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.dependencies.order_kinds import order_kinds_service
from gd_advanced_tools.schemas.order_kinds import OrderKindRequestSchema
from gd_advanced_tools.services.order_kinds import OrdersKindService


class APISKBKindService:

    def __init__(self):
        self.params = {'api-key': settings.api_settings.api_key}
        self.endpoint = settings.api_settings.skb_url + 'Kinds'

    async def get_request_kinds(self):
        request = httpx.get(self.endpoint, params=self.params)
        for el in request.json().get('Data'):
            data = {}
            data['name'] = el.get('Name')
            data['skb_uuid'] = el.get('Id')
            await order_kinds_service().add(schema=OrderKindRequestSchema(**data))
        return request.json().get('Data')
