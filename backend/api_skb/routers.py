from uuid import UUID

from fastapi import APIRouter, Header
from fastapi_utils.cbv import cbv

from backend.api_skb.enums import ResponseTypeChoices
from backend.api_skb.schemas import ApiOrderSchemaIn
from backend.api_skb.service import APISKBService


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class SKBCBV:
    """CBV-класс для создания запросов в СКБ-Техно."""

    service = APISKBService()

    @router.get("/get-kinds", summary="Получить справочник видов из СКБ Техно")
    async def get_skb_kinds(self, x_api_key: str = Header(...)):
        return await self.service.get_request_kinds()

    @router.post(
        "/create-request",
        summary="Создать запрос на получение данных по залогу в СКБ Техно",
    )
    async def add_request(
        self, request_schema: ApiOrderSchemaIn, x_api_key: str = Header(...)
    ):
        return await self.service.add_request(data=request_schema.model_dump())

    @router.get("/get-result", summary="Получить результат по залогу в СКБ Техно")
    async def get_skb_result(
        self,
        order_uuid: UUID,
        response_type: ResponseTypeChoices = ResponseTypeChoices.json,
        x_api_key: str = Header(...),
    ):
        return await self.service.get_response_by_order(
            order_uuid=order_uuid, response_type=response_type.value
        )
