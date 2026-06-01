"""W23.5 — FastAPI inbound router для зарегистрированных :class:`WebhookSource`.

Связывает HTTP-приём с ``SourceRegistry``: каждый POST на
``/webhooks/sources/{source_id}`` ищет соответствующий source kind=webhook
и делегирует ему ``verify_and_dispatch`` (HMAC + timestamp + emit).

Контракт намеренно отделён от ``webhook_router`` (он же
``handler.py``) — тот обслуживает legacy подписки/inbound через
``webhook_registry``. Новый router работает только с W23-Source-Registry.

Layer policy: entrypoints → core/interfaces (Protocol) + services/sources
(аксессоры). Конкретный класс ``WebhookSource`` (infrastructure) НЕ
импортируется — взаимодействие через duck typing + runtime-check kind.
"""

from __future__ import annotations

import logging
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException, Request

from src.backend.core.interfaces.source import SourceKind
from src.backend.services.sources import get_source_registry

__all__ = ("sources_router",)

logger = logging.getLogger(__name__)

sources_router = APIRouter(prefix="/webhooks/sources", tags=["Webhooks · W23 Sources"])


@sources_router.post(
    "/{source_id}",
    summary="Inbound webhook для зарегистрированного WebhookSource (W23)",
)
async def receive_source_webhook(source_id: str, request: Request) -> dict[str, Any]:
    """Принять webhook и делегировать его ``WebhookSource.verify_and_dispatch``.

    Args:
        source_id: Идентификатор source-инстанса в ``SourceRegistry``.
        request: HTTP-запрос (raw body + headers).

    Returns:
        Статус обработки события.

    Raises:
        HTTPException 404: Source не зарегистрирован или kind != webhook.
        HTTPException 401: Не прошла HMAC/timestamp валидация.
        HTTPException 400: Невалидный JSON в body.
    """
    registry = get_source_registry()
    try:
        source = registry.get(source_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=404, detail=f"WebhookSource {source_id!r} не зарегистрирован"
        ) from exc

    if source.kind is not SourceKind.WEBHOOK:
        raise HTTPException(
            status_code=404,
            detail=f"Source {source_id!r} имеет kind={source.kind.value}, ожидался webhook",
        )

    raw_body = await request.body()
    payload: Any = None
    if raw_body:
        try:
            payload = orjson.loads(raw_body)
        except orjson.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"Invalid JSON body: {exc}"
            ) from exc

    # Starlette ``Headers`` сами case-insensitive — отдаём как Mapping напрямую,
    # чтобы WebhookSource находил X-Signature/X-Timestamp независимо от регистра.
    headers = request.headers

    try:
        # WebhookSource (infra) экспортирует verify_and_dispatch, но это
        # не часть Protocol Source; kind-проверка выше гарантирует семантику.
        await source.verify_and_dispatch(  # type: ignore[attr-defined]
            raw_body, headers, payload=payload
        )
    except AttributeError as exc:
        raise HTTPException(
            status_code=500,
            detail=(
                f"Source {source_id!r} не предоставляет verify_and_dispatch — "
                "ожидался WebhookSource"
            ),
        ) from exc
    except Exception as exc:
        message = str(exc) or exc.__class__.__name__
        if exc.__class__.__name__ == "WebhookVerificationError":
            logger.warning(
                "Webhook verification failed: source=%s reason=%s", source_id, message
            )
            raise HTTPException(status_code=401, detail=message) from exc
        if isinstance(exc, RuntimeError):
            raise HTTPException(status_code=503, detail=message) from exc
        raise

    return {"status": "accepted", "source_id": source_id}
