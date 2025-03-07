from app.config.settings import settings
from app.grpc.protobuf.orders_pb2 import OrderResponse
from app.grpc.protobuf.orders_pb2_grpc import (
    OrderServiceServicer,
    add_OrderServiceServicer_to_server,
)
from app.services.route_services.orders import get_order_service
from app.utils.logging_service import grpc_logger


class OrderGRPCServicer(OrderServiceServicer):
    """
    Реализация gRPC сервиса для обработки операций с заказами.

    Атрибуты:
        order_service: Сервис для работы с заказами
        logger: Логгер для записи событий
    """

    def __init__(self):
        """Инициализация сервиса и подключение зависимостей"""
        self.order_service = get_order_service()
        self.logger = grpc_logger
        self.logger.info("Сервис заказов успешно инициализирован")

    async def CreateOrder(self, request, context):
        """
        Создание нового заказа через gRPC endpoint.

        Аргументы:
            request: CreateOrderRequest - запрос на создание заказа
            context: Контекст вызова gRPC

        Возвращает:
            OrderResponse: Ответ с результатом операции

        Исключения:
            Exception: Логирует ошибку и возвращает ответ с описанием проблемы
        """
        try:
            self.logger.info(f"Создание заказа с ID: {request.order_id}")

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
                f"Ошибка создания заказа: {str(exc)}", exc_info=True
            )
            return OrderResponse(error=str(exc))

    async def GetOrderResult(self, request, context):
        """
        Получение результатов обработки заказа.

        Аргументы:
            request: GetOrderRequest - запрос на получение результатов
            context: Контекст вызова gRPC

        Возвращает:
            OrderResponse: Ответ с данными о заказе

        Исключения:
            Exception: Логирует ошибку и возвращает ответ с описанием проблемы
        """
        try:
            self.logger.info(
                f"Запрос результатов для заказа: {request.order_id}"
            )

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
                f"Ошибка получения результатов: {str(exc)}", exc_info=True
            )
            return OrderResponse(error=str(exc))


async def serve():
    """
    Запуск gRPC сервера с использованием Unix Domain Socket.

    Выполняет:
    1. Очистку предыдущего socket-файла
    2. Инициализацию сервера с настройками из конфигурации
    3. Регистрацию сервиса
    4. Запуск и ожидание завершения работы сервера

    Исключения:
        KeyboardInterrupt: Обрабатывает graceful shutdown при прерывании
    """
    from pathlib import Path

    from concurrent import futures
    from grpc.aio import server

    # Очистка предыдущего socket-файла
    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    # Инициализация сервера с пулом потоков
    grpc_server = server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers),
        options=[
            ("grpc.so_reuseport", 1),
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
    )

    # Регистрация сервиса
    add_OrderServiceServicer_to_server(OrderGRPCServicer(), grpc_server)
    grpc_server.add_insecure_port(settings.grpc.socket_uri)

    # Запуск сервера
    await grpc_server.start()
    grpc_logger.info(f"Сервер запущен на {settings.grpc.socket_uri}")

    try:
        await grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        grpc_logger.info("Получен сигнал прерывания, остановка сервера...")
        await grpc_server.stop(5)


if __name__ == "__main__":
    from asyncio import run

    run(serve())
