import httpx

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.dependencies.order_kinds import order_kinds_service
from gd_advanced_tools.schemas.order_kinds import OrderKindSchemaIn


class APISKBKindService:

    def __init__(self):
        self.params = {'api-key': settings.api_settings.api_key}
        self.endpoint = settings.api_settings.skb_url 

    async def get_request_kinds(self):
        request = httpx.get(self.endpoint+'Kinds', params=self.params)
        for el in request.json().get('Data'):
            data = {}
            data['name'] = el.get('Name')
            data['skb_uuid'] = el.get('Id')
            await order_kinds_service().get_or_add(
                key='skb_uuid',
                value=el.get('Id'),
                schema=OrderKindSchemaIn(**data)
            )
        return request.json().get('Data')

    async def add_request(self):
        data = {}
        data['Id'] = '922e8e37-3537-44bb-ab93-1130f7c01888'
        data['OrderId'] = '922e8e37-3537-44bb-ab93-1130f7c01888'
        data['Number'] = '50:27:0020806:403'
        data['Priority'] = 80
        data['RequestType'] = 'e14f0565-83e8-440e-b0c0-f3396c7ba879'

        request = httpx.post(
            self.endpoint+'Create',
            params=self.params,
            data=data
        )
        return request.json()
