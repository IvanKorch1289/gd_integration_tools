from fastapi import APIRouter, status
from fastapi_utils.cbv import cbv

from gd_advanced_tools.schemas import OrderKindSchemaIn
from gd_advanced_tools.services import OrderKindService


__all__ = ('router', )


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    service = OrderKindService()

    @router.get(
        '/',
        status_code=status.HTTP_200_OK,
        summary='Получить все виды запросов'
    )
    async def get_kinds(self):
        return await self.service.all()

    @router.get(
        '/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Получить вид запроса по ID'
    )
    async def get_kind(self, kind_id: int):
        return await self.service.get(key='id', value=kind_id)

    @router.post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Добавить вид запроса'
    )
    async def add_kind(self, schema: OrderKindSchemaIn):
        return await self.service.add(schema=schema)

    @router.put(
        '/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Изменить вид запроса по ID'
    )
    async def update_kind(self, schema: OrderKindSchemaIn, kind_id: int):
        return await self.service.update(
            key='id',
            value=kind_id,
            schema=schema
        )

    @router.delete(
        '/{kind_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Удалить вид запроса по ID')
    async def delete_kind(self, kind_id: int):
        return await self.service.delete(key='id', value=kind_id)
