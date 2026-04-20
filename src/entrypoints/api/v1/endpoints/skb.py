from typing import Any

from fastapi import APIRouter, Depends, Response

from app.core.enums.skb import ResponseTypeChoices
from app.entrypoints.api.dependencies.auth import require_api_key
from app.entrypoints.api.generator.actions import ActionRouterBuilder, ActionSpec
from app.schemas.route_schemas.skb import (
    APISKBOrderSchemaIn,
    SKBObjectsByAddressQuerySchema,
    SKBOrdersListQuerySchema,
    SKBResultQuerySchema,
)
from app.services.integrations.skb import get_skb_service

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)


def build_skb_result_response(result: Any, action_kwargs: dict[str, Any]) -> Any:
    """Формирует HTTP-ответ для результата запроса из СКБ-Техно."""
    response_type = action_kwargs.get("response_type_str")

    if response_type == ResponseTypeChoices.pdf.value:
        return Response(
            content=result,
            media_type="application/pdf",
            headers={"Content-Disposition": "attachment; filename=result.pdf"},
        )

    return result


builder.add_actions(
    [
        ActionSpec(
            name="get_skb_kinds",
            method="GET",
            path="/get-kinds",
            summary="Получить справочник видов из СКБ Техно",
            service_getter=get_skb_service,
            service_method="get_request_kinds",
            dependencies=[Depends(require_api_key)],
            tags=("SKB",),
        ),
        ActionSpec(
            name="create_skb_request",
            method="POST",
            path="/create-request",
            summary="Создать запрос на получение данных по залогу в СКБ Техно",
            service_getter=get_skb_service,
            service_method="add_request",
            body_model=APISKBOrderSchemaIn,
            body_argument_name="data",
            dependencies=[Depends(require_api_key)],
            tags=("SKB",),
        ),
        ActionSpec(
            name="get_skb_result",
            method="GET",
            path="/get-result",
            summary="Получить результат по залогу в СКБ Техно",
            service_getter=get_skb_service,
            service_method="get_response_by_order",
            query_model=SKBResultQuerySchema,
            argument_aliases={"response_type": "response_type_str"},
            response_handler=build_skb_result_response,
            dependencies=[Depends(require_api_key)],
            tags=("SKB",),
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
        ),
        ActionSpec(
            name="get_skb_orders_list",
            method="GET",
            path="/get-orders-list",
            summary="Получить список заказов документов по залогу в СКБ Техно",
            service_getter=get_skb_service,
            service_method="get_orders_list",
            query_model=SKBOrdersListQuerySchema,
            dependencies=[Depends(require_api_key)],
            tags=("SKB",),
        ),
        ActionSpec(
            name="get_objects_by_address",
            method="POST",
            path="/get-objects-by-address",
            summary="Проверка-поиск объектов недвижимости по адресу",
            service_getter=get_skb_service,
            service_method="get_objects_by_address",
            query_model=SKBObjectsByAddressQuerySchema,
            dependencies=[Depends(require_api_key)],
            tags=("SKB",),
        ),
    ]
)
