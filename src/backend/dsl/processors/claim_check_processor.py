"""ClaimCheckProcessor — Claim Check EIP (Apache Camel) с S3 DI.

S38 W1: payload > threshold загружается в S3, через pipeline идёт только
``claim_ticket`` (s3 key). Получатель забирает payload обратно по ticket.

Directions:
    ``store``    — body > threshold → upload в S3 → set ``claim_ticket``.
                   body <= threshold → pass-through (no upload).
    ``retrieve`` — ``claim_ticket`` есть → download из S3 → set ``payload``.
                   ticket нет         → pass-through (no-op).

DI: ``s3_client`` — callable-провайдер, возвращающий объект с методами
``put_object(key, body, metadata)`` и ``get_object_bytes(key)``. По умолчанию
используется :func:`src.backend.infrastructure.external_apis.s3.get_s3_service`.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Callable, ClassVar

import orjson

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor, handle_processor_error

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("ClaimCheckProcessor",)


def _default_s3_provider() -> Callable[[], Any]:
    """Lazy S3-провайдер (избегает import при test-load)."""
    from src.backend.infrastructure.external_apis.s3 import get_s3_service

    def _p() -> Any:
        return get_s3_service()

    return _p


def _coerce_bytes(body: Any) -> bytes:
    """Сериализует body в bytes (bytes → as-is, иначе → orjson)."""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return orjson.dumps(body, default=str)


class ClaimCheckProcessor(BaseProcessor):
    """Claim Check EIP — S3 offload с DI-инжекцией s3_client."""

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        *,
        s3_bucket: str,
        s3_key_prefix: str = "claims/",
        threshold_bytes: int = 256 * 1024,
        s3_client: Callable[[], Any] | None = None,
        direction: str = "store",
        claim_field: str = "claim_ticket",
        payload_field: str = "payload",
        name: str | None = None,
    ) -> None:
        if direction not in ("store", "retrieve"):
            raise ValueError(
                f"direction должен быть store/retrieve, получено {direction!r}"
            )
        if threshold_bytes <= 0:
            raise ValueError(
                f"threshold_bytes должен быть > 0, получено {threshold_bytes}"
            )
        super().__init__(name=name or f"claim_check_{direction}")
        self._s3_bucket = s3_bucket
        self._s3_key_prefix = s3_key_prefix
        self._threshold = threshold_bytes
        self._s3_provider: Callable[[], Any] = s3_client or _default_s3_provider()
        self._direction = direction
        self._claim_field = claim_field
        self._payload_field = payload_field

    @handle_processor_error
    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        if self._direction == "store":
            await self._do_store(exchange)
        else:
            await self._do_retrieve(exchange)

    async def _do_store(self, exchange: "Exchange[Any]") -> None:
        body = exchange.in_message.body
        body_bytes = _coerce_bytes(body)
        if len(body_bytes) < self._threshold:
            return  # pass-through: ниже порога
        s3 = self._s3_provider()
        # UUID в ключе → idempotency (повторный store не перезапишет).
        claim_key = f"{self._s3_key_prefix}{uuid.uuid4().hex}"
        await s3.put_object(
            key=claim_key,
            body=body_bytes,
            metadata={
                "bucket": self._s3_bucket,
                "size": str(len(body_bytes)),
            },
        )
        exchange.set_property(self._claim_field, claim_key)
        exchange.set_property("claim_size", len(body_bytes))
        exchange.set_property("claim_bucket", self._s3_bucket)

    async def _do_retrieve(self, exchange: "Exchange[Any]") -> None:
        ticket = exchange.get_property(self._claim_field)
        if not ticket:
            return  # pass-through: ticket не задан
        s3 = self._s3_provider()
        payload = await s3.get_object_bytes(ticket)
        if payload is None:
            raise FileNotFoundError(f"Claim ticket not found в S3: {ticket}")
        exchange.set_property(self._payload_field, payload)

    def to_spec(self) -> dict[str, Any]:
        """Round-trip YAML spec для ClaimCheckProcessor."""
        return {
            "claim_check": {
                "s3_bucket": self._s3_bucket,
                "s3_key_prefix": self._s3_key_prefix,
                "threshold_bytes": self._threshold,
                "direction": self._direction,
                "claim_field": self._claim_field,
                "payload_field": self._payload_field,
            }
        }
