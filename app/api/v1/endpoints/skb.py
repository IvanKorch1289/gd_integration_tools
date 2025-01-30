from uuid import UUID

from fastapi import APIRouter, Header
from fastapi_utils.cbv import cbv

from app.schemas.route_schemas.skb import APISKBOrderSchemaIn
from app.services.route_services.skb import get_skb_service
from app.utils.enums.skb import ResponseTypeChoices


__all__ = ("router",)


router = APIRouter()


@cbv(router)
class SKBCBV:
    """
    CBV-класс для создания запросов в СКБ-Техно.

    Предоставляет методы для взаимодействия с API СКБ-Техно, включая получение справочника видов,
    создание запросов и получение результатов.
    """

    service = get_skb_service()

    @router.get("/get-kinds", summary="Получить справочник видов из СКБ Техно")
    async def get_skb_kinds(self, x_api_key: str = Header(...)):
        """
        Получить справочник видов запросов из СКБ-Техно.

        :param x_api_key: API-ключ для аутентификации.
        :return: Справочник видов запросов.
        """
        return await self.service.get_request_kinds()

    @router.post(
        "/create-request",
        summary="Создать запрос на получение данных по залогу в СКБ Техно",
    )
    async def add_request(
        self, request_schema: APISKBOrderSchemaIn, x_api_key: str = Header(...)
    ):
        """
        Создать запрос на получение данных по залогу в СКБ-Техно.

        :param request_schema: Данные для создания запроса.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат создания запроса.
        """
        return await self.service.add_request(data=request_schema.model_dump())

    @router.get("/get-result", summary="Получить результат по залогу в СКБ Техно")
    async def get_skb_result(
        self,
        order_uuid: UUID,
        response_type: ResponseTypeChoices = ResponseTypeChoices.json,
        x_api_key: str = Header(...),
    ):
        """
        Получить результат по залогу из СКБ-Техно.

        :param order_uuid: UUID запроса.
        :param response_type: Формат ответа (JSON или PDF). По умолчанию JSON.
        :param x_api_key: API-ключ для аутентификации.
        :return: Результат запроса в указанном формате.
        """
        return await self.service.get_response_by_order(
            order_uuid=order_uuid, response_type=response_type.value
        )
