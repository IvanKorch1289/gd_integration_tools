from grpc import RpcError
from grpc.aio import insecure_channel

from app.config.settings import settings
from app.grpc.protobuf.orders_pb2 import CreateOrderRequest, GetOrderRequest
from app.grpc.protobuf.orders_pb2_grpc import OrderServiceStub
from app.utils.logging_service import grpc_logger


class OrderGRPCClient:
    """Async gRPC client for order service"""

    def __init__(self):
        self.channel = None
        self.stub = None
        self.logger = grpc_logger

    async def get_settings(self):
        self.settings = settings.grpc

    async def connect(self):
        """Establish connection to gRPC server"""
        if not self.channel:
            await self.get_settings()

            self.channel = insecure_channel(
                self.settings.socket_uri,
                options=[
                    ("grpc.max_send_message_length", 100 * 1024 * 1024),
                    ("grpc.max_receive_message_length", 100 * 1024 * 1024),
                ],
            )
            self.stub = OrderServiceStub(self.channel)
            self.logger.info("Connected to gRPC server")

    async def create_order(self, order_id: int):
        """Create order through gRPC"""
        await self.connect()
        try:
            response = await self.stub.CreateOrder(
                CreateOrderRequest(order_id=order_id)
            )

            # if response.error != "":
            #     raise RuntimeError(response.error)
            print(response)
            return {
                "order_id": response.order_id,
                "skb_id": response.skb_id,
                "status": response.status,
            }
        except RpcError as exc:
            self.logger.error(
                f"gRPC error: {exc.code()}: {exc.details()}", exc_info=True
            )
            raise

    async def get_order_result(self, order_id: int, skb_id: str):
        """Get order result through gRPC"""
        await self.connect()
        try:
            response = await self.stub.GetOrderResult(
                GetOrderRequest(order_id=order_id, skb_id=skb_id)
            )
            if response.error:
                raise RuntimeError(response.error)
            return {
                "order_id": response.order_id,
                "status": response.status,
                "skb_id": response.skb_id,
            }
        except RpcError as exc:
            self.logger.error(
                f"gRPC error: {exc.code()}: {exc.details()}", exc_info=True
            )
            raise


# Singleton client instance
grpc_client = OrderGRPCClient()
