"""Webhook inbound + outbound handler.

Inbound: приём POST-запросов от внешних систем,
маршрутизация через DSL.
Outbound: отправка событий на зарегистрированные URL.
"""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from app.dsl.service import get_dsl_service
from app.entrypoints.webhook.registry import (
    WebhookSubscription,
    webhook_registry,
)

__all__ = ("webhook_router",)

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


# --- Подписки ---


class CreateSubscriptionRequest(BaseModel):
    """Запрос на создание webhook-подписки."""

    event_type: str = Field(description="Тип события.")
    target_url: str = Field(description="URL для отправки.")
    secret: str | None = Field(
        default=None, description="Секрет для HMAC."
    )


@webhook_router.post(
    "/subscriptions",
    summary="Создать подписку",
)
async def create_subscription(
    body: CreateSubscriptionRequest,
) -> dict[str, Any]:
    """Создаёт webhook-подписку."""
    sub = WebhookSubscription(
        event_type=body.event_type,
        target_url=body.target_url,
        secret=body.secret,
    )
    created = webhook_registry.add(sub)
    return {
        "id": created.id,
        "event_type": created.event_type,
        "target_url": created.target_url,
    }


@webhook_router.delete(
    "/subscriptions/{sub_id}",
    summary="Удалить подписку",
)
async def delete_subscription(sub_id: str) -> dict[str, str]:
    """Удаляет webhook-подписку."""
    try:
        webhook_registry.remove(sub_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "id": sub_id}


@webhook_router.get(
    "/subscriptions",
    summary="Список подписок",
)
async def list_subscriptions() -> list[dict[str, Any]]:
    """Возвращает все webhook-подписки."""
    return webhook_registry.list_all()


# --- Inbound webhook ---


@webhook_router.post(
    "/inbound/{event_type}",
    summary="Принять webhook",
)
async def receive_webhook(
    event_type: str,
    request: Request,
) -> dict[str, Any]:
    """Принимает входящий webhook и маршрутизирует через DSL.

    Args:
        event_type: Тип события (используется как route_id
            с префиксом ``webhook.``).
        request: HTTP-запрос с JSON body.
    """
    payload = await request.json()
    signature = request.headers.get("X-Webhook-Signature")

    logger.info(
        "Webhook inbound: event=%s, has_signature=%s",
        event_type,
        signature is not None,
    )

    try:
        dsl = get_dsl_service()
        route_id = f"webhook.{event_type}"

        exchange = await dsl.dispatch(
            route_id=route_id,
            body=payload,
            headers={
                "x-source": "webhook",
                "x-webhook-event": event_type,
                "x-webhook-signature": signature or "",
            },
        )

        return {
            "status": exchange.status.value,
            "error": exchange.error,
        }
    except KeyError:
        raise HTTPException(
            status_code=404,
            detail=f"Маршрут 'webhook.{event_type}' не найден",
        )


# --- Outbound webhook ---


async def send_webhook_event(
    event_type: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    """Отправляет событие на все подписанные URL.

    Args:
        event_type: Тип события.
        payload: Данные для отправки.

    Returns:
        Список результатов отправки.
    """
    import aiohttp

    subscriptions = webhook_registry.get_by_event(event_type)
    results: list[dict[str, Any]] = []

    for sub in subscriptions:
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Webhook-Event": event_type,
        }

        if sub.secret:
            import json

            body_bytes = json.dumps(payload).encode()
            sig = hmac.new(
                sub.secret.encode(),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()
            headers["X-Webhook-Signature"] = sig

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    sub.target_url,
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    results.append(
                        {
                            "subscription_id": sub.id,
                            "status": resp.status,
                            "success": 200 <= resp.status < 300,
                        }
                    )
        except Exception as exc:
            logger.exception(
                "Webhook outbound failed: sub=%s, url=%s",
                sub.id,
                sub.target_url,
            )
            results.append(
                {
                    "subscription_id": sub.id,
                    "status": None,
                    "success": False,
                    "error": str(exc),
                }
            )

    return results
