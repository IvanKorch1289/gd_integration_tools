"""gRPC-сервер с универсальным dispatch через ActionHandlerRegistry.

Все servicer-классы делегируют вызовы через единый _dispatch,
обеспечивая консистентность с другими протоколами.
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
    OrderServiceServicer,
    add_OrderServiceServicer_to_server,
)

grpc_logger = get_grpc_logger_provider()

# S17 K3 W3 (D12): helper для извлечения correlation_id вынесен в
# ``grpc/correlation.py`` (имп. наверху), чтобы тесты могли импортировать
# без protobuf-stubs (top-level ``invoker_pb2`` требует sys.path-magic).


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

    async def _dispatch(
        self,
        action: str,
        payload: dict[str, Any] | None = None,
        correlation_id: str | None = None,
        context: Any | None = None,
    ) -> Any:
        """Диспетчеризует action через общий `dispatch_action()`.

        IL-CRIT1.5: был дубликат ActionCommandSchema-сборки, теперь — через
        unified `app.entrypoints.base.dispatch_action` с `source="grpc"`.

        S17 K3 W3 (D12): если ``correlation_id`` не передан и доступен
        gRPC ``context`` — пытаемся извлечь ``x-correlation-id`` из incoming
        metadata; перед dispatch значение прокидывается в ContextVar через
        ``set_correlation_context``, чтобы downstream-цепочка
        (audit / outbox / outbound HTTP) увидела id.
        """
        if not correlation_id and context is not None:
            extracted = extract_correlation_id_from_grpc_context(context)
            if extracted:
                correlation_id = extracted
        if correlation_id:
            try:
                from src.backend.infrastructure.observability.correlation import (
                    set_correlation_context,
                )

                set_correlation_context(correlation_id=correlation_id)
            except ImportError:
                pass
        return await dispatch_action(
            action=action, payload=payload, source="grpc", correlation_id=correlation_id
        )

    def _serialize(self, result: Any) -> str:
        """Сериализует результат в JSON-строку."""
        if result is None:
            return "{}"
        if hasattr(result, "model_dump"):
            return encode_json(result.model_dump(mode="json")).decode("utf-8")
        if isinstance(result, (dict, list)):
            return encode_json(result).decode("utf-8")
        return str(result)


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


class InvokerGRPCServicer(InvokerServiceServicer):
    """Универсальный gRPC-адаптер для :class:`Invoker` (W22 этап B).

    Один rpc ``Invoke`` принимает :class:`InvokeRequest`, парсит JSON-поля
    payload/metadata и пробрасывает в :class:`Invoker.invoke`.
    Используется тот же ``app.state.invoker`` singleton, что и REST/WS/SOAP
    адаптеры, — гарантирует identical-результат для одного action из
    разных протоколов.
    """

    def __init__(self) -> None:
        self.logger = grpc_logger
        self.logger.info("InvokerGRPCServicer инициализирован")

    async def Invoke(  # type: ignore[no-untyped-def]
        self, request, context
    ):
        from src.backend.core.interfaces.invoker import (
            InvocationMode,
            InvocationRequest,
            InvocationStatus,
        )
        from src.backend.services.execution.invoker import get_invoker

        try:
            payload = orjson.loads(request.payload_json) if request.payload_json else {}
        except orjson.JSONDecodeError as exc:
            return InvokerInvokeResponse(
                invocation_id=request.invocation_id or "",
                status="error",
                mode=request.mode or InvocationMode.SYNC.value,
                error=f"Invalid payload_json: {exc}",
            )
        try:
            metadata = (
                orjson.loads(request.metadata_json) if request.metadata_json else {}
            )
        except orjson.JSONDecodeError as exc:
            return InvokerInvokeResponse(
                invocation_id=request.invocation_id or "",
                status="error",
                mode=request.mode or InvocationMode.SYNC.value,
                error=f"Invalid metadata_json: {exc}",
            )

        try:
            mode = InvocationMode(request.mode) if request.mode else InvocationMode.SYNC
        except ValueError:
            return InvokerInvokeResponse(
                invocation_id=request.invocation_id or "",
                status="error",
                mode=request.mode or InvocationMode.SYNC.value,
                error=f"Unknown mode: {request.mode!r}",
            )

        invocation_request = InvocationRequest(
            action=request.action,
            payload=dict(payload) if isinstance(payload, dict) else {},
            mode=mode,
            reply_channel=request.reply_channel or None,
            metadata=dict(metadata) if isinstance(metadata, dict) else {},
        )
        if request.invocation_id:
            invocation_request = InvocationRequest(
                action=invocation_request.action,
                payload=invocation_request.payload,
                mode=invocation_request.mode,
                reply_channel=invocation_request.reply_channel,
                invocation_id=request.invocation_id,
                metadata=invocation_request.metadata,
            )

        invoker = get_invoker()
        try:
            response = await invoker.invoke(invocation_request)
        except Exception as exc:
            cid = uuid.uuid4().hex[:12]
            self.logger.exception("Invoke ошибка [ref=%s]", cid)
            return InvokerInvokeResponse(
                invocation_id=invocation_request.invocation_id,
                status=InvocationStatus.ERROR.value,
                mode=mode.value,
                error=_safe_error(exc, cid),
            )

        result_json = ""
        if response.result is not None:
            try:
                if hasattr(response.result, "model_dump"):
                    result_json = encode_json(
                        response.result.model_dump(mode="json")
                    ).decode("utf-8")
                else:
                    result_json = encode_json(response.result).decode("utf-8")
            except Exception:
                result_json = str(response.result)

        return InvokerInvokeResponse(
            invocation_id=response.invocation_id,
            status=response.status.value,
            mode=response.mode.value,
            result_json=result_json,
            error=response.error or "",
        )


def _load_tls_credentials() -> "grpc.ServerCredentials | None":
    """Загружает TLS-credentials из settings.grpc. None — если TLS отключён.

    Ожидаемые файлы: server_cert.pem, server_key.pem, optional ca_cert.pem
    (для mTLS с проверкой клиентских сертификатов).
    """
    from pathlib import Path

    import grpc

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

    async def intercept_service(
        self, continuation: Any, handler_call_details: Any
    ) -> Any:
        from grpc import StatusCode
        from grpc.aio import AbortError

        metadata = dict(handler_call_details.invocation_metadata or [])
        key = metadata.get("x-api-key") or metadata.get(
            "authorization", ""
        ).removeprefix("Bearer ")
        if not key or key != self._expected_key:
            grpc_logger.warning(
                "gRPC unauthenticated request: method=%s", handler_call_details.method
            )

            async def _abort(_request_or_iterator: Any, context: Any) -> None:
                try:
                    await context.abort(
                        StatusCode.UNAUTHENTICATED, "invalid or missing API key"
                    )
                except AbortError:
                    raise

            return _abort
        return await continuation(handler_call_details)


async def serve() -> None:
    """Запуск gRPC-сервера с регистрацией всех servicer."""
    from concurrent import futures
    from pathlib import Path

    from grpc.aio import server

    Path(settings.grpc.socket_path).unlink(missing_ok=True)

    interceptors = []
    api_key = getattr(settings.secure, "api_key", None)
    if api_key:
        interceptors.append(AuthInterceptor(expected_key=api_key))

    executor = futures.ThreadPoolExecutor(max_workers=settings.grpc.max_workers)
    grpc_server = server(
        executor,
        options=[
            ("grpc.so_reuseport", 1),
            # S163 W19: use settings.grpc.* instead of hardcoded 100MB.
            # Per W13 GRPCSettings — max_message_size_bytes, keepalive_*,
            # max_concurrent_streams.
            (
                "grpc.max_send_message_length",
                settings.grpc.max_message_size_bytes,
            ),
            (
                "grpc.max_receive_message_length",
                settings.grpc.max_message_size_bytes,
            ),
        ],
        interceptors=interceptors,
    )

    add_OrderServiceServicer_to_server(OrderGRPCServicer(), grpc_server)
    add_InvokerServiceServicer_to_server(InvokerGRPCServicer(), grpc_server)

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
        grpc_logger.info(
            "gRPC сервер запущен с TLS (mTLS=%s)",
            bool(getattr(settings.grpc, "require_client_auth", False)),
        )

    await grpc_server.start()
    grpc_logger.info("gRPC-сервер запущен на %s", settings.grpc.socket_uri)

    try:
        await grpc_server.wait_for_termination()
    except KeyboardInterrupt:
        grpc_logger.info("Остановка gRPC-сервера...")
    finally:
        await grpc_server.stop(5)
        executor.shutdown(wait=True)


if __name__ == "__main__":
    from asyncio import run

    run(serve())
