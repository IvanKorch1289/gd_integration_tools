from typing import List
from fastapi import APIRouter, Request, status
from fastapi_utils.cbv import cbv

from gd_advanced_tools.src.core.transaction import transaction
from gd_advanced_tools.src.core.schemas import Response, ResponseMulti
from gd_advanced_tools.src.kinds.models import OrderKind
from gd_advanced_tools.src.kinds.schemas import OrderKindRequestSchema, OrderKindResponseSchema
from gd_advanced_tools.src.kinds.repository import OrdersKindRepository


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    @router.get('/', status_code=status.HTTP_200_OK, summary='Получить все виды запросов')
    @transaction
    async def get_kinds(self, request: Request) -> ResponseMulti[OrderKindResponseSchema]:
        orders_public = [
            OrderKindResponseSchema.model_validate(order) async for order in OrdersKindRepository().all()
        ]
        return ResponseMulti[OrderKindResponseSchema](result=orders_public)

    @router.get('/{kind_id}', status_code=status.HTTP_200_OK, summary='Получить вид запроса по ID')
    @transaction
    async def get_kind(self, request: Request, kind_id: int):
        order = await OrdersKindRepository().get(key='id', value=kind_id)
        orders_public = OrderKindResponseSchema.model_validate(order)
        return Response[OrderKindResponseSchema](result=orders_public)

    @router.post('/', status_code=status.HTTP_201_CREATED, summary='Добавить вид запроса')
    @transaction
    async def add_kind(self, request: Request, schema: OrderKindRequestSchema) -> Response[OrderKindResponseSchema]:
        order: OrderKind = await OrdersKindRepository().add(schema=schema)
        order_public = OrderKindRequestSchema.model_validate(order)
        return Response[OrderKindResponseSchema](result=order_public)

    @router.put('/{kind_id}', summary='Изменить вид запроса по ID')
    async def update_kind(self, request: Request, schema: OrderKindRequestSchema, kind_id: int) -> Response[OrderKindResponseSchema]:
        order: OrderKind = await OrdersKindRepository().update(key='id', value=kind_id, schema=schema)
        order_public = OrderKindRequestSchema.model_validate(order)
        return Response[OrderKindResponseSchema](result=order_public)


    @router.delete('/{kind_id}', summary='Удалить вид запроса по ID')
    async def delete_kind(self, request: Request, kind_id: int):
        return await OrdersKindRepository()._delete(id=kind_id)
