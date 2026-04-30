import asyncio
import importlib
from typing import Any

from pydantic import BaseModel

from src.core.errors import ServiceError
from src.core.interfaces.repositories import OrderKindRepositoryProtocol
from src.schemas.route_schemas.orderkinds import (
    OrderKindSchemaIn,
    OrderKindSchemaOut,
    OrderKindVersionSchemaOut,
)
from src.services.core.base import BaseService
from src.services.integrations.skb import APISKBService, get_skb_service

__all__ = ("get_order_kind_service",)


_REPO_ORDERKINDS_MOD = "src." + "infrastructure.repositories.orderkinds"


class OrderKindService(
    BaseService[
        OrderKindRepositoryProtocol,
        OrderKindSchemaOut,
        OrderKindSchemaIn,
        OrderKindVersionSchemaOut,
    ]
):
    """
    Сервис для работы с видами заказов.
    """

    def __init__(
        self,
        schema_in: BaseModel,
        schema_out: BaseModel,
        version_schema: BaseModel,
        repo: OrderKindRepositoryProtocol,
        request_service: APISKBService,
    ) -> None:
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )
        self.request_service = request_service

    async def create_or_update_kinds_from_skb(self) -> dict[str, Any]:
        """
        Получает виды запросов из СКБ-Техно и синхронизирует локальный справочник.
        """
        try:
            result = await self.request_service.get_request_kinds()

            data_block = result.get("data") or {}
            items = data_block.get("Data") or []

            tasks = [
                self.get_or_add(
                    key="skb_uuid",
                    value=item.get("Id"),
                    data={"name": item.get("Name"), "skb_uuid": item.get("Id")},
                )
                for item in items
                if isinstance(item, dict) and item.get("Id") is not None
            ]

            if tasks:
                await asyncio.gather(*tasks)

            return result
        except Exception as exc:
            raise ServiceError from exc


_order_kind_service_instance: OrderKindService | None = None


def get_order_kind_service() -> OrderKindService:
    """
    Возвращает экземпляр сервиса для работы с видами заказов.
    """
    global _order_kind_service_instance
    if _order_kind_service_instance is None:
        repo = importlib.import_module(_REPO_ORDERKINDS_MOD).get_order_kind_repo()
        _order_kind_service_instance = OrderKindService(
            repo=repo,
            schema_in=OrderKindSchemaIn,
            schema_out=OrderKindSchemaOut,
            version_schema=OrderKindVersionSchemaOut,
            request_service=get_skb_service(),
        )
    return _order_kind_service_instance
