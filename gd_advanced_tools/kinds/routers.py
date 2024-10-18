from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv
from sqlalchemy.ext.asyncio import AsyncSession

from gd_advanced_tools.core.database import db_helper
from gd_advanced_tools.kinds.schemas import OrderKindAddSchema, OrderKindGetSchema
from gd_advanced_tools.kinds.services import OrderKindRepository


router = APIRouter()


@cbv(router)
class KindCBV:
    """CBV-класс для работы со справочником видов запросов."""

    session: AsyncSession = Depends(db_helper.get_session)

    @router.get('/', summary='Получить все виды запросов')
    async def get_kinds(self) -> list[OrderKindGetSchema]:
        return await OrderKindRepository.get_tasks(session=self.session)

    @router.get('/{kind_id}', summary='Получить вид запроса по ID')
    async def get_kind(self, kind_id: int) -> OrderKindGetSchema:
        return await OrderKindRepository.get_task_by_id(kind_id=kind_id, session=self.session)

    @router.post('/', summary='Добавить вид запроса')
    async def add_kind(self, order_kind: OrderKindAddSchema = Depends()) -> OrderKindGetSchema:
        return await OrderKindRepository.add_kind(kind=order_kind, session=self.session)

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
        return await OrderKindRepository.delete_kind(kind_id=kind_id, session=self.session)
