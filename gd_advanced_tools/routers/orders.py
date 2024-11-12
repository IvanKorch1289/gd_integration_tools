from fastapi import APIRouter, status
from fastapi_utils.cbv import cbv

from gd_advanced_tools.enums.api_skb import ResponseTypeChoices
from gd_advanced_tools.schemas import OrderSchemaIn
from gd_advanced_tools.services import OrderService


__all__ = ('router', )


router = APIRouter()


@cbv(router)
class OrderCBV:
    """CBV-класс для работы с запросами."""

    service = OrderService()

    @router.get(
        '/',
        status_code=status.HTTP_200_OK,
        summary='Получить все запросы'
    )
    async def get_orders(self):
        return await self.service.all()

    @router.get(
        '/{order_id}',
        status_code=status.HTTP_200_OK,
        summary='Получить запрос по ID'
    )
    async def get_order(self, order_id: int):
        return await self.service.get(key='id', value=order_id)

    @router.post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Добавить запрос'
    )
    async def add_order(self, schema: OrderSchemaIn):
        return await self.service.add(data=schema.model_dump())

    @router.put(
        '/{order_id}',
        status_code=status.HTTP_200_OK,
        summary='Изменить запроса по ID'
    )
    async def update_order(self, schema: OrderSchemaIn, order_id: int):
        return await self.service.update(
            key='id',
            value=order_id,
            data=schema.model_dump()
        )

    @router.delete(
        '/{order_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Удалить запрос по ID')
    async def delete_order(self, order_id: int):
        return await self.service.delete(key='id', value=order_id)

    @router.get(
        '/{order_id}/get-result',
        status_code=status.HTTP_200_OK,
        summary='Получить результат запроса')
    async def get_order_result(
        self,
        order_id: int,
        response_type: ResponseTypeChoices = ResponseTypeChoices.json
    ):
        return await self.service.get_order_result(order_id=order_id, response_type=response_type)
