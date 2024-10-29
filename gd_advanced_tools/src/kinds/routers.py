from fastapi import APIRouter, Depends, status
from fastapi_utils.cbv import cbv

from gd_advanced_tools.src.core.transaction import transaction
from gd_advanced_tools.src.core.schemas import Response, ResponseMulti
from gd_advanced_tools.src.kinds.schemas import OrderKindPublic, OrderKindCreateRequestBody
from gd_advanced_tools.src.kinds.repository import OrdersKindRepository


router = APIRouter()


@cbv(router)
class OrderKindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    @router.get('/', status_code=status.HTTP_200_OK, summary='Получить все виды запросов')
    @transaction
    async def get_kinds(self) -> ResponseMulti[OrderKindPublic]:
        orders_public = [
            OrderKindPublic.model_validate(order) async for order in OrdersKindRepository()._all()
        ]
        return ResponseMulti[OrderKindPublic](result=orders_public)

    @router.get('/{kind_id}', status_code=status.HTTP_200_OK, summary='Получить вид запроса по ID')
    @transaction
    async def get_kind(self, kind_id: int) -> Response[OrderKindPublic]:
        order = OrdersKindRepository._get(key='id', value=kind_id)
        return await Response[OrderKindPublic](result=order)

    @router.post('/', status_code=status.HTTP_201_CREATED, summary='Добавить вид запроса')
    @transaction
    async def add_kind(self,  schema: OrderKindCreateRequestBody) -> Response[OrderKindPublic]:
        order: Order = OrdersKindRepository.add(OrderKindCreateRequestBody(**payload))
        order_public = OrderKindPublic.model_validate(order)

        return Response[OrderKindPublic](result=order_public)

    # @router.put('/{kind_id}', summary='Изменить вид запроса по ID')
    # async def update_kind(self, order_kind: OrderKindAddSchema = Depends()) -> OrderKindGetSchema:
    #     return await OrderKindRepository.
    #     await self.session.execute(
    #         update(OrderKind)
    #         .where(OrderKind.id == kind_id)
    #         .values(name=order_kind.name, description=order_kind.description, skb_uuid=order_kind.skb_uuid)
    #     )
    #     try:
    #         await self.session.commit()
    #         return status.HTTP_200_OK
    #     except Exception as ex:
    #         await self.session.rollback()
    #         return ex

    @router.delete('/{kind_id}', summary='Удалить вид запроса по ID')
    async def delete_kind(self, kind_id: int):
        return await OrdersKindRepository._delete(kind_id=kind_id)
