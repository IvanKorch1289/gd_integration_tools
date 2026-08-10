"""Shared DLQ enqueue helper для MQ subscribers (cycle-5/D-AUDIT-504).

Используется :mod:`subscribers` и :mod:`invoker_subscribers` для
fail-loud DLQ handoff при exception в handler'е (B-17 pattern).

Если ``stream_dlq_writer`` не настроен в composition root → log warning
и drop (fail-loud signal для observability). Если DLQ write сам
падает — log error (poison message не теряется молча).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.providers import get_stream_dlq_writer_provider
from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason

__all__ = ("enqueue_mq_poison_message",)


def _summarize_body(body: Any, *, max_len: int = 256) -> str:
    """Краткое summary body для metadata (truncate to ``max_len``)."""
    try:
        rendered = repr(body)
    except (TypeError, ValueError) as repr_exc:
        # cycle-9/D-AUDIT-1013: narrow exceptions + observability (mirror
        # D-AUDIT-1011/1012 для stream).
        # TypeError для unrepresentable type, ValueError для invalid repr
        # value.
        import logging
        logging.getLogger(__name__).debug(
            "stream_dlq_helper.summarize_body_fallback",
            extra={"error": str(repr_exc)},
        )
        rendered = "<unrepresentable body>"
    if len(rendered) > max_len:
        return rendered[: max_len - 3] + "..."
    return rendered


async def enqueue_mq_poison_message(
    *,
    exc: BaseException,
    body: Any,
    source: str,
    route_id: str,
    correlation_id: str | None,
    tenant_id: str | None = None,
    logger: Any,
) -> None:
    """Enqueue poison message в DLQ с poison_message summary.

    cycle-5/D-AUDIT-504: B-17 fail-loud pattern для MQ subscribers.
    При exception в handler'е → enqueue в DLQWriter + logger.error
    с poison_message, tenant_id, correlation_id.

    Args:
        exc: исключение из handler'а.
        body: исходный body (original payload для replay).
        source: ``"redis"`` / ``"rabbit"`` (broker name).
        route_id: stream/queue name (для per-route DLQ retention).
        correlation_id: OpenTelemetry/клиентский correlation id.
        tenant_id: tenant id (если извлекается из body/meta).
        logger: stream_logger (для fallback warning/error logs).
    """
    writer = get_stream_dlq_writer_provider()
    if writer is None:
        # Fail-loud: composition root не вызвал
        # ``set_stream_dlq_writer_provider``. Не теряем событие молча —
        # log warning (видно в observability dashboard).
        logger.warning(
            "MQ poison message dropped (DLQ writer not configured): "
            "source=%s route_id=%s correlation_id=%s tenant_id=%s err_class=%s",
            source,
            route_id,
            correlation_id,
            tenant_id,
            type(exc).__name__,
        )
        return

    envelope = DLQEnvelope(
        transport=f"mq:{source}",
        route_id=route_id,
        original_payload=body,
        error_class=type(exc).__name__,
        error_message=str(exc),
        reason=DLQReason.UNEXPECTED,
        tenant_id=tenant_id,
        metadata={
            "correlation_id": correlation_id,
            "poison_message": _summarize_body(body),
        },
    )
    try:
        await writer.write(envelope)
    except Exception as dlq_exc:
        # DLQ writer сам упал — log error, но НЕ raise (handler уже
        # в except-блоке; исключение из DLQ-write не должно маскировать
        # исходную ошибку).
        logger.error(
            "MQ poison message DLQ enqueue failed: source=%s route_id=%s "
            "correlation_id=%s tenant_id=%s err_class=%s dlq_err=%s",
            source,
            route_id,
            correlation_id,
            tenant_id,
            type(exc).__name__,
            dlq_exc,
            exc_info=True,
        )
