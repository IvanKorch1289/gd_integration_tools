from typing import Any

from fastapi import APIRouter, Depends, Response

from src.backend.core.enums.skb import ResponseTypeChoices, response_type_value
from src.backend.core.extension_registry import get_extension_resource
from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
)
from src.backend.services.integrations.skb import get_skb_service

__all__ = ("router",)


# ADR-0457: объекты расширения получаются через core-реестр (инверсия
# зависимости ``src/ → extensions``), а не прямым импортом ``extensions.*``.
# Резолв на уровне модуля — FastAPI строит модель при импорте.
APISKBOrderSchemaIn = get_extension_resource("skb", "schema", "api_skb_order_in")
SKBObjectsByAddressQuerySchema = get_extension_resource(
    "skb", "schema", "objects_by_address"
)
SKBOrdersListQuerySchema = get_extension_resource("skb", "schema", "orders_list")
SKBResultQuerySchema = get_extension_resource("skb", "schema", "result")


router = APIRouter()
builder = ActionRouterBuilder(router)


def build_skb_result_response(result: Any, action_kwargs: dict[str, Any]) -> Any:
    """Сформировать HTTP-ответ для результата запроса из СКБ-Техно.

    Args:
        result: Результат, полученный от сервиса (JSON или bytes документа).
        action_kwargs: Аргументы вызова action'а; ``response_type_str`` —
            тип ответа (enum-член или строка).

    Returns:
        PDF-ответ с вложением либо исходный результат.
    """
    response_type = response_type_value(action_kwargs.get("response_type_str"))

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
