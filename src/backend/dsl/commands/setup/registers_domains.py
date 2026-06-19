"""S66 W2 — registers_domains.py part of setup.py decomp.

domain entity registrations (orders, files, dadata, admin, etc.).

Functions: _register_orders, _register_files, _register_skb_api, _register_dadata, _register_tech, _register_admin, _register_servicedsl_auto_register.
"""

from __future__ import annotations

from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry
from src.backend.dsl.commands.setup.helpers import (
    _register_crud_actions,  # S66 W2: cross-import
)


def _register_orders() -> None:
    from extensions.core_entities.orders.services.orders import get_order_service
    from extensions.core_entities.orders.schemas.route import OrderIdQuerySchema

    _register_crud_actions("orders", get_order_service)

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="orders.create_skb_order",
                service_getter=get_order_service,
                service_method="create_skb_order",
                payload_model=OrderIdQuerySchema,
            ),
            ActionHandlerSpec(
                action="orders.get_result",
                service_getter=get_order_service,
                service_method="get_order_result",
            ),
            ActionHandlerSpec(
                action="orders.get_file_and_json",
                service_getter=get_order_service,
                service_method="get_order_file_and_json_from_skb",
                payload_model=OrderIdQuerySchema,
            ),
            ActionHandlerSpec(
                action="orders.get_file_from_storage",
                service_getter=get_order_service,
                service_method="get_order_file_from_storage",
                payload_model=OrderIdQuerySchema,
            ),
            ActionHandlerSpec(
                action="orders.get_file_base64",
                service_getter=get_order_service,
                service_method="get_order_file_from_storage_base64",
                payload_model=OrderIdQuerySchema,
            ),
            ActionHandlerSpec(
                action="orders.get_file_link",
                service_getter=get_order_service,
                service_method="get_order_file_from_storage_link",
                payload_model=OrderIdQuerySchema,
            ),
            ActionHandlerSpec(
                action="orders.send_order_data",
                service_getter=get_order_service,
                service_method="send_order_data",
                payload_model=OrderIdQuerySchema,
            ),
        ]
    )


def _register_files() -> None:
    from src.backend.services.io.files import get_file_service

    _register_crud_actions("files", get_file_service)


def _register_skb_api() -> None:
    from extensions.skb.schemas.route import (
        APISKBOrderSchemaIn,
        SKBObjectsByAddressQuerySchema,
        SKBOrdersListQuerySchema,
        SKBResultQuerySchema,
    )
    from src.backend.services.integrations.skb import get_skb_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="skb.get_request_kinds",
                service_getter=get_skb_service,
                service_method="get_request_kinds",
            ),
            ActionHandlerSpec(
                action="skb.add_request",
                service_getter=get_skb_service,
                service_method="add_request",
                payload_model=APISKBOrderSchemaIn,
            ),
            ActionHandlerSpec(
                action="skb.get_response_by_order",
                service_getter=get_skb_service,
                service_method="get_response_by_order",
                payload_model=SKBResultQuerySchema,
            ),
            ActionHandlerSpec(
                action="skb.get_orders_list",
                service_getter=get_skb_service,
                service_method="get_orders_list",
                payload_model=SKBOrdersListQuerySchema,
            ),
            ActionHandlerSpec(
                action="skb.get_objects_by_address",
                service_getter=get_skb_service,
                service_method="get_objects_by_address",
                payload_model=SKBObjectsByAddressQuerySchema,
            ),
        ]
    )


def _register_dadata() -> None:
    from extensions.dadata.schemas.route import DadataGeolocateQuerySchema
    from src.backend.services.integrations.dadata import get_dadata_service

    action_handler_registry.register(
        action="dadata.get_geolocate",
        service_getter=get_dadata_service,
        service_method="get_geolocate",
        payload_model=DadataGeolocateQuerySchema,
    )


def _register_tech() -> None:
    from src.backend.schemas.base import EmailSchema
    from src.backend.services.core.tech import get_tech_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="tech.check_all_services",
                service_getter=get_tech_service,
                service_method="check_all_services",
            ),
            ActionHandlerSpec(
                action="tech.check_database",
                service_getter=get_tech_service,
                service_method="check_database",
            ),
            ActionHandlerSpec(
                action="tech.check_redis",
                service_getter=get_tech_service,
                service_method="check_redis",
            ),
            ActionHandlerSpec(
                action="tech.check_s3",
                service_getter=get_tech_service,
                service_method="check_s3",
            ),
            ActionHandlerSpec(
                action="tech.send_email",
                service_getter=get_tech_service,
                service_method="send_email",
                payload_model=EmailSchema,
            ),
        ]
    )


def _register_admin() -> None:
    from src.backend.services.core.admin import get_admin_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="admin.get_config",
                service_getter=get_admin_service,
                service_method="get_config",
            ),
            ActionHandlerSpec(
                action="admin.list_cache_keys",
                service_getter=get_admin_service,
                service_method="list_cache_keys",
            ),
            ActionHandlerSpec(
                action="admin.get_cache_value",
                service_getter=get_admin_service,
                service_method="get_cache_value",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_cache",
                service_getter=get_admin_service,
                service_method="invalidate_cache",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_cache_by_pattern",
                service_getter=get_admin_service,
                service_method="invalidate_cache_by_pattern",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_cache_by_tag",
                service_getter=get_admin_service,
                service_method="invalidate_cache_by_tag",
            ),
            ActionHandlerSpec(
                action="admin.invalidate_table",
                service_getter=get_admin_service,
                service_method="invalidate_table",
            ),
        ]
    )


def _register_servicedsl_auto_register() -> None:

    from src.backend.dsl.service_dsl import (
        scan_and_register_actions,
        service_dsl_registry,
    )

    service_dsl_registry.register_all_actions()
    scan_and_register_actions(
        [
            "src.backend.services",
            "src.backend.entrypoints.webhook",
            "src.backend.services.integrations",
        ]
    )
