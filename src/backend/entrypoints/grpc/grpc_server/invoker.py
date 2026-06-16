"""S65 W3 — invoker.py part of grpc_server decomp.

Classes: InvokerGRPCServicer.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

import orjson

from src.backend.core.serialization.msgspec_hotpath import encode_json

if TYPE_CHECKING:
    pass

from src.backend.core.di.providers import get_grpc_logger_provider
from src.backend.entrypoints.grpc.grpc_server._safe_error import _safe_error
from src.backend.entrypoints.grpc.protobuf.invoker_pb2 import (  # type: ignore
    InvokeResponse as InvokerInvokeResponse,
)
from src.backend.entrypoints.grpc.protobuf.invoker_pb2_grpc import (
    InvokerServiceServicer,
)

grpc_logger = get_grpc_logger_provider()

# S17 K3 W3 (D12): helper для извлечения correlation_id вынесен в
# ``grpc/correlation.py`` (имп. наверху), чтобы тесты могли импортировать
# без protobuf-stubs (top-level ``invoker_pb2`` требует sys.path-magic).


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
