from fastapi import APIRouter, Depends, status

from src.core.config.settings import settings
from src.core.enums.invocation import BrokerKind
from src.entrypoints.api.dependencies.auth import require_api_key
from src.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
    CrudSpec,
)
from src.entrypoints.api.generator.invocation import (
    EventPublishSpec,
    InvocationSpec,
    build_http_command_meta,
    default_payload_factory,
)
from src.schemas.filter_schemas.orders import OrderFilter
from src.schemas.route_schemas.orders import (
    OrderIdPathSchema,
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from src.services.core.orders import get_order_service
from src.services.decorators.limiting import route_limiting

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)

common_dependencies = [Depends(require_api_key)]
common_decorators = [route_limiting]
common_tags = ("Orders",)

internal_actions_stream = settings.redis.get_stream_name("actions")


builder.add_crud_resource(
    CrudSpec(
        name="orders",
        service_getter=get_order_service,
        schema_in=OrderSchemaIn,
        schema_out=OrderSchemaOut,
        version_schema=OrderVersionSchemaOut,
        filter_class=OrderFilter,
        dependencies=common_dependencies,
        decorators=common_decorators,
        tags=common_tags,
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)


builder.add_actions(
    [
        ActionSpec(
            name="create_skb_order",
            method="POST",
            path="/{order_id}/create-skb-order",
            summary="Создать запрос в СКБ-Техно",
            description=(
                "Единый action для создания запроса в СКБ-Техно. "
                "Поддерживает direct/event/delayed/cron."
            ),
            service_getter=get_order_service,
            service_method="create_skb_order",
            path_model=OrderIdPathSchema,
            status_code=status.HTTP_200_OK,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
            invocation=InvocationSpec(
                event=EventPublishSpec(
                    action="orders.create_skb_order",
                    broker=BrokerKind.redis,
                    destination=internal_actions_stream,
                    payload_factory=default_payload_factory,
                    meta_factory=build_http_command_meta,
                )
            ),
        ),
        ActionSpec(
            name="fetch_order_result",
            method="POST",
            path="/{order_id}/fetch-result",
            summary="Получить результат заказа",
            description=(
                "Единый action для получения результата заказа из СКБ-Техно. "
                "Поддерживает direct/event/delayed/cron."
            ),
            service_getter=get_order_service,
            service_method="get_order_file_and_json_from_skb",
            path_model=OrderIdPathSchema,
            status_code=status.HTTP_200_OK,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
            invocation=InvocationSpec(
                event=EventPublishSpec(
                    action="orders.fetch_result",
                    broker=BrokerKind.redis,
                    destination=internal_actions_stream,
                    payload_factory=default_payload_factory,
                    meta_factory=build_http_command_meta,
                )
            ),
        ),
        ActionSpec(
            name="send_order_result",
            method="POST",
            path="/{order_id}/send-result",
            summary="Отправить результат заказа",
            description=(
                "Единый action для отправки результата заказа в downstream pipeline. "
                "Поддерживает direct/event/delayed/cron."
            ),
            service_getter=get_order_service,
            service_method="send_order_data",
            path_model=OrderIdPathSchema,
            status_code=status.HTTP_200_OK,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
            invocation=InvocationSpec(
                event=EventPublishSpec(
                    action="orders.send_result",
                    broker=BrokerKind.redis,
                    destination=internal_actions_stream,
                    payload_factory=default_payload_factory,
                    meta_factory=build_http_command_meta,
                )
            ),
        ),
        ActionSpec(
            name="get_order_file",
            method="GET",
            path="/{order_id}/file",
            summary="Получить файл заказа",
            description="Получает файл заказа из хранилища.",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage",
            path_model=OrderIdPathSchema,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_order_file_base64",
            method="GET",
            path="/{order_id}/file-base64",
            summary="Получить файл заказа в Base64",
            description="Получает файлы заказа в формате Base64.",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage_base64",
            path_model=OrderIdPathSchema,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_order_file_link",
            method="GET",
            path="/{order_id}/file-link",
            summary="Получить ссылку на файл заказа",
            description="Получает ссылки на скачивание файлов заказа.",
            service_getter=get_order_service,
            service_method="get_order_file_from_storage_link",
            path_model=OrderIdPathSchema,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_order_payload_with_links",
            method="GET",
            path="/{order_id}/payload-with-links",
            summary="Получить JSON результата и ссылки на файлы",
            description="Возвращает результат заказа и ссылки на файлы.",
            service_getter=get_order_service,
            service_method="get_order_file_link_and_json_result_for_request",
            path_model=OrderIdPathSchema,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
        ),
        ActionSpec(
            name="get_order_payload_with_base64",
            method="GET",
            path="/{order_id}/payload-with-base64",
            summary="Получить JSON результата и файлы в Base64",
            description="Возвращает результат заказа и файлы в формате Base64.",
            service_getter=get_order_service,
            service_method="get_order_file_base64_and_json_result_for_request",
            path_model=OrderIdPathSchema,
            dependencies=common_dependencies,
            decorators=common_decorators,
            tags=common_tags,
        ),
    ]
)
