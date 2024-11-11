from gd_advanced_tools.models import Order
from gd_advanced_tools.repository import OrderRepository
from gd_advanced_tools.schemas import (
    PublicModel,
    OrderSchemaOut,
    ApiOrderSchemaIn,
    Response
)
from gd_advanced_tools.services.base import BaseService
from gd_advanced_tools.services.api_skb import APISKBService


__all__ = ('OrderService', )


class OrderService(BaseService):

    repo = OrderRepository()
    response_schema = OrderSchemaOut

    async def add(self, schema: PublicModel) -> PublicModel | None:
        kind_uuid = schema.order_kind_id
        order: Response = await super().add(schema=schema)
        if order:
            data = {}
            data['Id'] = order.result.object_uuid
            data['OrderId'] = order.result.object_uuid
            data['Number'] = order.result.pledge_cadastral_number
            data['Priority'] = 80
            data['RequestType'] = kind_uuid

            request_schema = ApiOrderSchemaIn.model_validate(data)

            request = await APISKBService().add_request(schema=request_schema)
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
