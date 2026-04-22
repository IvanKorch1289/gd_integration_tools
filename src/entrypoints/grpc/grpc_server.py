"""gRPC-сервер с универсальным dispatch через ActionHandlerRegistry.

Все servicer-классы делегируют вызовы через единый _dispatch,
обеспечивая консистентность с другими протоколами.
"""

import uuid
from typing import Any

import orjson

from app.core.config.settings import settings
from app.core.errors import BaseError
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


def _safe_error(exc: Exception, correlation_id: str) -> str:
    """Формирует безопасное сообщение об ошибке для gRPC client (IL-CRIT1.2).

    Политика:
      * ``BaseError`` (наши domain errors) — выдаём ``exc.message`` как есть:
        это типизированные, контролируемые сообщения без sensitive data.
      * Любые другие Exception — generic "Internal server error" +
        correlation_id для корреляции с server-side logs.

    Никогда не отправляем клиенту ``str(exc)`` / traceback / module-path —
    это leak информации о внутренней реализации (кроме контролируемых
    BaseError сообщений).
    """
    if isinstance(exc, BaseError):
        return exc.message
    return f"Internal server error; ref={correlation_id}"


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
            return orjson.dumps(result.model_dump(mode="json")).decode()
        if isinstance(result, (dict, list)):
            return orjson.dumps(result).decode()
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
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "CreateOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))

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
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "GetOrderResult ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))

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
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "GetOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderDetailResponse(error=_safe_error(exc, cid))

    async def DeleteOrder(self, request, context):
        try:
            await self._dispatch("orders.delete", {"key": "id", "value": request.order_id})
            return OrderDeleteResponse(success=True)
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "DeleteOrder ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderDeleteResponse(success=False, error=_safe_error(exc, cid))

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
            cid = uuid.uuid4().hex[:12]
            self.logger.error(
                "SendOrderData ошибка [ref=%s]: %s", cid, exc, exc_info=True
            )
            return OrderResponse(error=_safe_error(exc, cid))


def _load_tls_credentials() -> "grpc.ServerCredentials | None":
    """Загружает TLS-credentials из settings.grpc. None — если TLS отключён.

    Ожидаемые файлы: server_cert.pem, server_key.pem, optional ca_cert.pem
    (для mTLS с проверкой клиентских сертификатов).
    """
    import grpc
    from pathlib import Path

    tls = getattr(settings.grpc, "tls_enabled", False)
    if not tls:
        return None

    cert_path = Path(getattr(settings.grpc, "server_cert_path", ""))
    key_path = Path(getattr(settings.grpc, "server_key_path", ""))
    if not (cert_path.exists() and key_path.exists()):
        raise RuntimeError(
            "gRPC TLS включён, но server_cert_path/server_key_path не найдены."
        )

    server_cert = cert_path.read_bytes()
    server_key = key_path.read_bytes()
    ca_path = Path(getattr(settings.grpc, "ca_cert_path", "") or "")
    ca_cert = ca_path.read_bytes() if ca_path.exists() else None

    require_client_auth = bool(getattr(settings.grpc, "require_client_auth", False))

    return grpc.ssl_server_credentials(
        [(server_key, server_cert)],
        root_certificates=ca_cert,
        require_client_auth=require_client_auth,
    )


class AuthInterceptor:
    """gRPC server interceptor — проверяет API-ключ в metadata.

    Используется совместно с TLS (ADR-004): TLS обеспечивает канал,
    AuthInterceptor — authn/authz уровня приложения.
    """

    def __init__(self, expected_key: str) -> None:
        self._expected_key = expected_key

    async def intercept_service(self, continuation, handler_call_details):
        from grpc import StatusCode
        from grpc.aio import AbortError

        metadata = dict(handler_call_details.invocation_metadata or [])
        key = metadata.get("x-api-key") or metadata.get("authorization", "").removeprefix("Bearer ")
        if not key or key != self._expected_key:
            grpc_logger.warning(
                "gRPC unauthenticated request: method=%s",
                handler_call_details.method,
            )

            async def _abort(request_or_iterator, context):
                try:
                    await context.abort(StatusCode.UNAUTHENTICATED, "invalid or missing API key")
                except AbortError:
                    raise

            return _abort
        return await continuation(handler_call_details)


async def serve():
    """Запуск gRPC-сервера с регистрацией всех servicer."""
    from concurrent import futures
    from pathlib import Path

    from grpc.aio import server

    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    interceptors = []
    api_key = getattr(settings.secure, "api_key", None)
    if api_key:
        interceptors.append(AuthInterceptor(expected_key=api_key))

    grpc_server = server(
        futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers),
        options=[
            ("grpc.so_reuseport", 1),
            ("grpc.max_send_message_length", 100 * 1024 * 1024),
            ("grpc.max_receive_message_length", 100 * 1024 * 1024),
        ],
        interceptors=interceptors,
    )

    add_OrderServiceServicer_to_server(OrderGRPCServicer(), grpc_server)

    credentials = _load_tls_credentials()
    if credentials is None:
        # dev/local-only: unix-socket или loopback. Запрещено в prod через
        # валидацию в settings.grpc (ADR-004).
        grpc_server.add_insecure_port(settings.grpc.socket_uri)
        grpc_logger.warning(
            "gRPC сервер запущен без TLS — допустимо только для dev/unix-socket."
        )
    else:
        grpc_server.add_secure_port(settings.grpc.socket_uri, credentials)
        grpc_logger.info("gRPC сервер запущен с TLS (mTLS=%s)", bool(getattr(settings.grpc, "require_client_auth", False)))

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
