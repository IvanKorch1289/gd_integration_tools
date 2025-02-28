from app.config.settings import settings
from app.grpc.protobuf.orders_pb2 import OrderResponse
from app.grpc.protobuf.orders_pb2_grpc import (
    OrderServiceServicer,
    add_OrderServiceServicer_to_server,
)
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import grpc_logger


class OrderGRPCServicer(OrderServiceServicer):
    """gRPC servicer handling order operations"""

    def __init__(self):
        self.order_service = get_order_service()
        self.logger = grpc_logger

        self.logger.info("Order service initialized")

    async def CreateOrder(self, request, context):
        """Create order implementation for gRPC endpoint"""
        try:
            self.logger.info(f"Creating order for ID: {request.order_id}")

            result = await self.order_service.create_skb_order(
                order_id=request.order_id
            )

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error=(
                    ""
                    if result["response"]["status_code"] == 200
                    else str(result["response"]["status_code"])
                ),
            )
        except Exception as exc:
            self.logger.error(
                f"Order creation failed: {str(exc)}", exc_info=True
            )
            return OrderResponse(error=str(exc))

    async def GetOrderResult(self, request, context):
        """Get order result implementation for gRPC endpoint"""
        try:
            self.logger.info(f"Fetching result for order: {request.order_id}")

            result = await self.order_service.get_order_file_and_json_from_skb(
                order_id=request.order_id
            )

            return OrderResponse(
                order_id=result["instance"]["id"],
                skb_id=str(result["instance"]["object_uuid"]),
                status=str(result["response"]["status_code"]),
                error=(
                    ""
                    if result["response"]["status_code"] == 200
                    else str(result["response"]["status_code"])
                ),
            )
        except Exception as exc:
            self.logger.error(
                f"Result fetch failed: {str(exc)}", exc_info=True
            )
            return OrderResponse(error=str(exc))


async def serve():
    """Start gRPC server with Unix domain socket"""
    from pathlib import Path

    from concurrent import futures
    from grpc.aio import server

    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    server = server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers),
        options=[
            ("grpc.so_reuseport", 1),
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
    )

    add_OrderServiceServicer_to_server(OrderGRPCServicer(), server)
    server.add_insecure_port(settings.grpc.socket_uri)

    await server.start()
    grpc_logger.info(f"Server started on {settings.grpc.socket_uri}")

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        await server.stop(5)


if __name__ == "__main__":
    import asyncio

    asyncio.run(serve())
