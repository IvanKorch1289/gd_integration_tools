
import sys
import traceback
from gd_advanced_tools.enums.api_skb import ResponseTypeChoices
from gd_advanced_tools.repository import OrderRepository
from gd_advanced_tools.schemas import (
    PublicModel,
    OrderSchemaOut
)
from gd_advanced_tools.services.base import BaseService
from gd_advanced_tools.services.api_skb import APISKBService


__all__ = ('OrderService', )


class OrderService(BaseService):

    repo = OrderRepository()
    request_service = APISKBService()
    response_schema = OrderSchemaOut

    async def add(self, data: dict) -> PublicModel | None:
        kind_uuid = data['order_kind_id']
        order = await super().add(data=data)
        if order:
            data = {}
            data['Id'] = order.result.object_uuid
            data['OrderId'] = order.result.object_uuid
            data['Number'] = order.result.pledge_cadastral_number
            data['Priority'] = 80
            data['RequestType'] = kind_uuid

            request = await self.request_service.add_request(data=data)
            if not request['Result']:
                update_data = {}
                update_data['is_active'] = False
                update_data['errors'] = request['Message']
                await self.repo.update(
                    key='id',
                    value=order.result.id,
                    data=update_data
                )

                return 'Ошибка отправки запроса в СКБ-Техно'
            return request

    async def get_order_result(
        self,
        order_id: int,
        response_type: ResponseTypeChoices
    ):
        try:
            instance = await self.repo.get(key='id', value=order_id)
            result = await self.request_service.get_response_by_order(
                order_uuid=instance.object_uuid,
                response_type=response_type.value
            )
            if result['Result']:
                update_data = {}
                update_data['is_active'] = False
                update_data['errors'] = result['Message']
                update_data['response_data'] = result['Data']
                await self.repo.update(
                    key='id',
                    value=instance.id,
                    data=update_data
                )
                return result['Data']
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return 'Ошибка'
