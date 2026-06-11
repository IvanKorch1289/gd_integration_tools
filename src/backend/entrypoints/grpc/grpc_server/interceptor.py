from __future__ import annotations
"""S65 W3 — interceptor.py part of grpc_server decomp.

Classes: AuthInterceptor.
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



