"""S65 W3 — base.py part of grpc_server decomp.

Classes: BaseGRPCServicer.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.serialization.msgspec_hotpath import encode_json

if TYPE_CHECKING:
    pass

from src.backend.core.di.providers import get_grpc_logger_provider
from src.backend.entrypoints.base import dispatch_action
from src.backend.entrypoints.grpc.correlation import (
    extract_correlation_id_from_grpc_context,
)

grpc_logger = get_grpc_logger_provider()

# S17 K3 W3 (D12): helper для извлечения correlation_id вынесен в
# ``grpc/correlation.py`` (имп. наверху), чтобы тесты могли импортировать
# без protobuf-stubs (top-level ``invoker_pb2`` требует sys.path-magic).


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
                from src.backend.core.observability.correlation import (
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
