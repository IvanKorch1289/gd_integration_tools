from uuid import UUID

from fastapi import APIRouter, Header, Response
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

    @router.get(
        "/get-result",
        summary="Получить результат по залогу в СКБ Техно",
        responses={
            200: {
                "content": {
                    "application/json": {},
                    "application/pdf": {},
                    "application/octet-stream": {},
                },
                "description": "Возвращает результат в формате JSON или PDF.",
            }
        },
    )
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
        result = await self.service.get_response_by_order(
            order_uuid=order_uuid, response_type_str=response_type.value
        )

        if response_type == ResponseTypeChoices.pdf:
            # Если запрошен PDF, возвращаем StreamingResponse
            return Response(
                content=result,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": "attachment; filename=result.pdf"
                },
            )
        else:
            # Если запрошен JSON, возвращаем JSONResponse
            return result

    @router.get(
        "/get-orders-list",
        summary="Получить список заказов документов по залогу в СКБ Техно",
    )
    async def get_orders_list(
        self,
        take: int | None = None,
        skip: int | None = None,
        x_api_key: str = Header(...),
    ):
        """
        Получить список заказов документов по залогу в СКБ Техно.

        :param take: Количество запросов, которые нужно выбрать.
        :param skip: Количесnво запросов, которые нужно пропустить
        :param x_api_key: API-ключ для аутентификации.
        :return: Список созданных заказов.
        """
        return await self.service.get_orders_list(take=take, skip=skip)

    @router.post(
        "/get-objects-by-address",
        summary="Проверка-поиск объектов недвижимости по адресу (ФИАС/КЛАДР).",
    )
    async def get_objects_by_address(
        self,
        query: str,
        comment: str | None = None,
        x_api_key: str = Header(...),
    ):
        """
        Проверка-поиск объектов недвижимости по адресу (ФИАС/КЛАДР).

        :param query: Адрес.
        :param comment: Коментарий
        :param x_api_key: API-ключ для аутентификации.
        :return: Список объектов.
        """
        return await self.service.get_objects_by_address(
            query=query, comment=comment
        )
