from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi_utils.cbv import cbv

from backend.api_skb.enums import ResponseTypeChoices
from backend.api_skb.service import APISKBService
from backend.core.auth import security


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class SKBCBV:
    """CBV-класс для создания запросов в СКБ-Техно."""

    service = APISKBService()

    @router.get("/get-kinds", summary="Получить справочник видов из СКБ Техно")
    async def get_skb_kinds(self):
        return await self.service.get_request_kinds()

    @router.post(
        "/create-request",
        summary="Создать запрос на получение данных по залогу в СКБ Техно",
        dependencies=[Depends(security.access_token_required)],
    )
    async def add_request(self):
        return await self.service.add_request()

    @router.get(
        "/get-result",
        summary="Получить результат на получение данных по залогу в СКБ Техно",
        dependencies=[Depends(security.access_token_required)],
    )
    async def get_result(
        self,
        order_uuid: UUID,
        response_type: ResponseTypeChoices = ResponseTypeChoices.json,
    ):
        return await self.service.get_response_by_order(
            order_uuid=order_uuid, response_type=response_type.value
        )
