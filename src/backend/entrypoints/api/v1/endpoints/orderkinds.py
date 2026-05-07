from fastapi import APIRouter, Depends, status

from src.backend.core.config.settings import settings
from src.backend.core.enums.invocation import BrokerKind
from src.backend.entrypoints.api.dependencies.auth import require_api_key
from src.backend.entrypoints.api.generator.actions import (
    ActionRouterBuilder,
    ActionSpec,
    CrudSpec,
)
from src.backend.entrypoints.api.generator.invocation import (
    EventPublishSpec,
    InvocationSpec,
    build_http_command_meta,
    default_payload_factory,
)
from src.backend.entrypoints.dependencies.rate_limit import get_default_rate_limiter
from src.backend.schemas.filter_schemas.orderkinds import OrderKindFilter
from src.backend.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from src.backend.services.core.orderkinds import get_order_kind_service

__all__ = ("router",)


router = APIRouter()
builder = ActionRouterBuilder(router)

common_dependencies = [Depends(require_api_key), Depends(get_default_rate_limiter())]
common_tags = ("OrderKinds",)


builder.add_crud_resource(
    CrudSpec(
        name="orderkinds",
        service_getter=get_order_kind_service,
        schema_in=OrderKindSchemaIn,
        schema_out=OrderKindSchemaOut,
        version_schema=OrderKindVersionSchemaOut,
        filter_class=OrderKindFilter,
        dependencies=common_dependencies,
        tags=common_tags,
        id_param_name="object_id",
        id_field_name="id",
        default_order_by="id",
    )
)


builder.add_actions(
    [
        ActionSpec(
            name="create_or_update_kinds_from_skb",
            method="POST",
            path="/create_or_update_from_skb/",
            summary="Синхронизировать виды запросов из СКБ-Техно",
            description=(
                "Загружает виды запросов из СКБ-Техно и выполняет "
                "создание или обновление локального справочника. "
                "Поддерживает direct, event и scheduled execution."
            ),
            service_getter=get_order_kind_service,
            service_method="create_or_update_kinds_from_skb",
            status_code=status.HTTP_200_OK,
            dependencies=common_dependencies,
            tags=common_tags,
            invocation=InvocationSpec(
                event=EventPublishSpec(
                    action="orderkinds.sync_from_skb",
                    broker=BrokerKind.redis,
                    destination=settings.redis.get_stream_name("actions"),
                    payload_factory=default_payload_factory,
                    meta_factory=build_http_command_meta,
                )
            ),
        )
    ]
)
