"""gRPC-сервер с универсальным dispatch через ActionHandlerRegistry.

Все servicer-классы делегируют вызовы через единый _dispatch,
обеспечивая консистентность с другими протоколами.
"""

import json
from typing import Any

from app.core.config.settings import settings
from app.dsl.commands.registry import action_handler_registry
from app.entrypoints.grpc.protobuf.orders_pb2 import (  # type: ignore
    DeleteResponse as OrderDeleteResponse,
    OrderDetailResponse,
    OrderResponse,
)
from app.entrypoints.grpc.protobuf.orders_pb2_grpc import (
    OrderServiceServicer,
    add_OrderServiceServicer_to_server,
)
from app.infrastructure.external_apis.logging_service import grpc_logger
from app.schemas.invocation import ActionCommandSchema


class BaseGRPCServicer:
    """Базовый класс для gRPC servicer с dispatch через ActionHandlerRegistry."""

    def __init__(self) -> None:
        self.logger = grpc_logger

    async def _dispatch(self, action: str, payload: dict[str, Any] | None = None) -> Any:
        """Диспетчеризует action через ActionHandlerRegistry."""
        command = ActionCommandSchema(
            action=action,
            payload=payload or {},
            meta={"source": "grpc"},
        )
        return await action_handler_registry.dispatch(command)

    def _serialize(self, result: Any) -> str:
        """Сериализует результат в JSON-строку."""
        if result is None:
            return "{}"
        if hasattr(result, "model_dump"):
            return json.dumps(result.model_dump(mode="json"), default=str)
        if isinstance(result, (dict, list)):
            return json.dumps(result, default=str)
        return str(result)


class OrderGRPCServicer(BaseGRPCServicer, OrderServiceServicer):
    """gRPC servicer для Orders."""

    def __init__(self) -> None:
        super().__init__()
        self.logger.info("OrderGRPCServicer инициализирован")

    async def CreateOrder(self, request, context):
        try:
            result = await self._dispatch(
                "orders.create_skb_order",
                {"order_id": request.order_id},
            )
            if not result:
                return OrderResponse(error="Не удалось создать заказ")

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error="" if result["response"]["status_code"] == 200 else str(result["response"]["status_code"]),
            )
        except Exception as exc:
            self.logger.error("CreateOrder ошибка: %s", exc, exc_info=True)
            return OrderResponse(error=str(exc))

    async def GetOrderResult(self, request, context):
        try:
            result = await self._dispatch(
                "orders.get_file_and_json",
                {"order_id": request.order_id},
            )
            if not result:
                return OrderResponse(error="Результат не найден")

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error="" if result["response"]["status_code"] == 200 else str(result["response"]["status_code"]),
            )
        except Exception as exc:
            self.logger.error("GetOrderResult ошибка: %s", exc, exc_info=True)
            return OrderResponse(error=str(exc))

    async def GetOrder(self, request, context):
        try:
            result = await self._dispatch(
                "orders.get",
                {"key": "id", "value": request.order_id},
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
            self.logger.error("GetOrder ошибка: %s", exc, exc_info=True)
            return OrderDetailResponse(error=str(exc))

    async def DeleteOrder(self, request, context):
        try:
            await self._dispatch("orders.delete", {"key": "id", "value": request.order_id})
            return OrderDeleteResponse(success=True)
        except Exception as exc:
            self.logger.error("DeleteOrder ошибка: %s", exc, exc_info=True)
            return OrderDeleteResponse(success=False, error=str(exc))

    async def CreateSKBOrder(self, request, context):
        return await self.CreateOrder(request, context)

    async def GetFileAndJson(self, request, context):
        return await self.GetOrderResult(request, context)

    async def SendOrderData(self, request, context):
        try:
            result = await self._dispatch(
                "orders.send_order_data",
                {"order_id": request.order_id},
            )
            if not result:
                return OrderResponse(error="Не удалось отправить данные")
            return OrderResponse(
                order_id=request.order_id,
                status="sent",
                json_data=self._serialize(result),
            )
        except Exception as exc:
            self.logger.error("SendOrderData ошибка: %s", exc, exc_info=True)
            return OrderResponse(error=str(exc))


async def serve():
    """Запуск gRPC-сервера с регистрацией всех servicer."""
    from concurrent import futures
    from pathlib import Path

    from grpc.aio import server

    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    grpc_server = server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers),
        options=[
            ("grpc.so_reuseport", 1),
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
    )

    add_OrderServiceServicer_to_server(OrderGRPCServicer(), grpc_server)
    grpc_server.add_insecure_port(settings.grpc.socket_uri)

    await grpc_server.start()
    grpc_logger.info("gRPC-сервер запущен на %s", settings.grpc.socket_uri)

    try:
        await grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        grpc_logger.info("Остановка gRPC-сервера...")
        await grpc_server.stop(5)


if __name__ == "__main__":
    from asyncio import run

    run(serve())
