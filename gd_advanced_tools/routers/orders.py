from fastapi import APIRouter, status
from fastapi_utils.cbv import cbv

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
        return await self.service.add(schema=schema)

    @router.put(
        '/{order_id}',
        status_code=status.HTTP_200_OK,
        summary='Изменить запроса по ID'
    )
    async def update_order(self, schema: OrderSchemaIn, order_id: int):
        return await self.service.update(
            key='id',
            value=order_id,
            schema=schema
        )

    @router.delete(
        '/{order_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Удалить вид запроса по ID')
    async def delete_order(self, order_id: int):
        return await self.service.delete(key='id', value=order_id)
