from __future__ import annotations
"""S65 W3 — order.py part of grpc_server decomp.

Classes: OrderGRPCServicer.
"""

import uuid
from typing import TYPE_CHECKING, Any

import orjson

from src.backend.core.serialization.msgspec_hotpath import encode_json

if TYPE_CHECKING:
    import grpc

from src.backend.core.config.settings import settings
from src.backend.core.di.providers import get_grpc_logger_provider
from src.backend.core.errors import BaseError
from src.backend.entrypoints.base import dispatch_action
from src.backend.entrypoints.grpc.correlation import (
    extract_correlation_id_from_grpc_context,
)
from src.backend.entrypoints.grpc.protobuf.invoker_pb2 import (  # type: ignore
    InvokeResponse as InvokerInvokeResponse,
)
from src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc import (
    InvokerServiceServicer,
    add_InvokerServiceServicer_to_server,
)
from src.backend.entrypoints.grpc.protobuf.orders_pb2 import (  # type: ignore
    DeleteResponse as OrderDeleteResponse,
)
from src.backend.entrypoints.grpc.protobuf.orders_pb2 import (  # type: ignore[attr-defined]
    OrderDetailResponse,
    OrderResponse,
)
from src.backend.entrypoints.grpc.protobuf.orders_pb2_grpc import (
from src.backend.entrypoints.grpc.grpc_server.base import BaseGRPCServicer  # S65 W3: cross-import

    OrderServiceServicer,
    add_OrderServiceServicer_to_server,
)

grpc_logger = get_grpc_logger_provider()

# S17 K3 W3 (D12): helper для извлечения correlation_id вынесен в
# ``grpc/correlation.py`` (имп. наверху), чтобы тесты могли импортировать
# без protobuf-stubs (top-level ``invoker_pb2`` требует sys.path-magic).




class OrderGRPCServicer(BaseGRPCServicer, OrderServiceServicer):
    """gRPC servicer для Orders."""

    def __init__(self) -> None:
        super().__init__()
        self.logger.info("OrderGRPCServicer инициализирован")

    async def CreateOrder(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        try:
            result = await self._dispatch(
                "orders.create_skb_order", {"order_id": request.order_id}
            )
            if not result:
                return OrderResponse(error="Не удалось создать заказ")

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error=""
                if result["response"]["status_code"] == 200
                else str(result["response"]["status_code"]),
            )
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "CreateOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))

    async def GetOrderResult(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        try:
            result = await self._dispatch(
                "orders.get_file_and_json", {"order_id": request.order_id}
            )
            if not result:
                return OrderResponse(error="Результат не найден")

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error=""
                if result["response"]["status_code"] == 200
                else str(result["response"]["status_code"]),
            )
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "GetOrderResult ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))

    async def GetOrder(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        try:
            result = await self._dispatch(
                "orders.get", {"key": "id", "value": request.order_id}
            )
            if not result:
                return OrderDetailResponse(error="Заказ не найден")

            return OrderDetailResponse(
                id=result.id if hasattr(result, "id") else 0,
                object_uuid=str(getattr(result, "object_uuid", "")),
                order_kind_id=getattr(result, "order_kind_id", 0) or 0,
                is_active=getattr(result, "is_active", True),
                is_send_to_gd=getattr(result, "is_send_to_gd", False),
                json_data=self._serialize(result),
            )
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error("GetOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True)
            return OrderDetailResponse(error=_safe_error(exc, cid))

    async def DeleteOrder(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        try:
            await self._dispatch(
                "orders.delete", {"key": "id", "value": request.order_id}
            )
            return OrderDeleteResponse(success=True)
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "DeleteOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderDeleteResponse(success=False, error=_safe_error(exc, cid))

    async def CreateSKBOrder(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        return await self.CreateOrder(request, context)

    async def GetFileAndJson(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        return await self.GetOrderResult(request, context)

    async def SendOrderData(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        try:
            result = await self._dispatch(
                "orders.send_order_data", {"order_id": request.order_id}
            )
            if not result:
                return OrderResponse(error="Не удалось отправить данные")
            return OrderResponse(
                order_id=request.order_id,
                status="sent",
                json_data=self._serialize(result),
            )
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "SendOrderData ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))



