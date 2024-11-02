from typing import Annotated
from fastapi import APIRouter, Depends, status
from fastapi_utils.cbv import cbv

from gd_advanced_tools.dependencies.order_kinds import order_kinds_service
from gd_advanced_tools.schemas.order_kinds import OrderKindSchemaIn
from gd_advanced_tools.services.order_kinds import OrdersKindService


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    @router.get(
        '/',
        status_code=status.HTTP_200_OK,
        summary='Получить все виды запросов'
    )
    async def get_kinds(
        self,
        service: Annotated[OrdersKindService, Depends(order_kinds_service)]
    ):
        return await service.all()

    @router.get(
        '/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Получить вид запроса по ID'
    )
    async def get_kind(
        self,
        kind_id: int,
        service: Annotated[OrdersKindService, Depends(order_kinds_service)]
    ):
        return await service.get(key='id', value=kind_id)

    @router.post(
        '/',
        status_code=status.HTTP_201_CREATED,
        summary='Добавить вид запроса'
    )
    async def add_kind(
        self,
        schema: OrderKindSchemaIn,
        service: Annotated[OrdersKindService, Depends(order_kinds_service)]
    ):
        return await service.add(schema=schema)

    @router.put(
        '/{kind_id}',
        status_code=status.HTTP_200_OK,
        summary='Изменить вид запроса по ID'
    )
    async def update_kind(
        self,
        schema: OrderKindSchemaIn, kind_id: int,
        service: Annotated[OrdersKindService, Depends(order_kinds_service)]
    ):
        return await service.update(key='id', value=kind_id, schema=schema)

    @router.delete(
        '/{kind_id}',
        status_code=status.HTTP_204_NO_CONTENT,
        summary='Удалить вид запроса по ID')
    async def delete_kind(
        self,
        kind_id: int,
        service: Annotated[OrdersKindService, Depends(order_kinds_service)]
    ):
        return await service.delete(key='id', value=kind_id)
