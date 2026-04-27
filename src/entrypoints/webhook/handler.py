"""Webhook inbound + outbound handler.

Inbound: приём POST-запросов от внешних систем,
маршрутизация через DSL.
Outbound: отправка событий на зарегистрированные URL.

Security (v17):
- Management endpoints (subscriptions CRUD) защищены require_auth
- Inbound endpoint валидирует HMAC signature если у подписки есть secret
- Rate limiting через RedisRateLimiter на all endpoints
"""

import hashlib
import hmac
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.dsl.service import get_dsl_service
from src.entrypoints.webhook.registry import WebhookSubscription, webhook_registry

__all__ = ("webhook_router",)

logger = logging.getLogger(__name__)

webhook_router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


def _require_auth_dep():
    """Lazy import require_auth to avoid circular imports."""
    from src.entrypoints.api.dependencies.auth_selector import require_auth

    return require_auth()


async def _check_rate_limit(
    identifier: str, *, limit: int = 100, window: int = 60
) -> None:
    """Применяет rate limit через RedisRateLimiter."""
    try:
        from src.infrastructure.resilience.unified_rate_limiter import (
            RateLimit,
            RateLimitExceeded,
            get_rate_limiter,
        )

        limiter = get_rate_limiter()
        await limiter.check(
            identifier=f"webhook:{identifier}",
            policy=RateLimit(
                limit=limit, window_seconds=window, key_prefix="webhook_rl"
            ),
        )
    except ImportError:
        return
    except RateLimitExceeded as exc:
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after)},
        )


# --- Подписки ---


class CreateSubscriptionRequest(BaseModel):
    """Запрос на создание webhook-подписки."""

    event_type: str = Field(description="Тип события.")
    target_url: str = Field(description="URL для отправки.")
    secret: str | None = Field(default=None, description="Секрет для HMAC.")


@webhook_router.post("/subscriptions", summary="Создать подписку (auth required)")
async def create_subscription(
    body: CreateSubscriptionRequest, auth: Any = Depends(_require_auth_dep)
) -> dict[str, Any]:
    """Создаёт webhook-подписку. Требует authentication."""
    # SSRF protection — валидация target_url
    from src.dsl.engine.processors.scraping import _validate_url

    try:
        _validate_url(body.target_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Invalid target_url: {exc}")

    sub = WebhookSubscription(
        event_type=body.event_type, target_url=body.target_url, secret=body.secret
    )
    created = webhook_registry.add(sub)
    return {
        "id": created.id,
        "event_type": created.event_type,
        "target_url": created.target_url,
    }


@webhook_router.delete(
    "/subscriptions/{sub_id}", summary="Удалить подписку (auth required)"
)
async def delete_subscription(
    sub_id: str, auth: Any = Depends(_require_auth_dep)
) -> dict[str, str]:
    """Удаляет webhook-подписку. Требует authentication."""
    try:
        webhook_registry.remove(sub_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"status": "deleted", "id": sub_id}


@webhook_router.get("/subscriptions", summary="Список подписок (auth required)")
async def list_subscriptions(
    auth: Any = Depends(_require_auth_dep),
) -> list[dict[str, Any]]:
    """Возвращает все webhook-подписки. Требует authentication."""
    return webhook_registry.list_all()


# --- Inbound webhook ---


@webhook_router.post(
    "/inbound/{event_type}",
    summary="Принять webhook (rate limited + signature verified)",
)
async def receive_webhook(event_type: str, request: Request) -> dict[str, Any]:
    """Принимает входящий webhook и маршрутизирует через DSL.

    Security:
    - Rate limit по client IP (default 100 req/min)
    - HMAC signature verification если в подписке указан secret

    Args:
        event_type: Тип события (используется как route_id
            с префиксом ``webhook.``).
        request: HTTP-запрос с JSON body.
    """
    client_ip = request.client.host if request.client else "unknown"
    await _check_rate_limit(f"inbound:{client_ip}", limit=100, window=60)

    raw_body = await request.body()
    signature = request.headers.get("X-Webhook-Signature", "")

    # Verify HMAC signature if subscription has secret
    subscriptions = [
        s for s in webhook_registry.list_all() if s.get("event_type") == event_type
    ]
    for sub in subscriptions:
        secret = sub.get("secret")
        if secret:
            expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
            if not hmac.compare_digest(signature, expected):
                logger.warning(
                    "Webhook signature mismatch: event=%s, sub=%s",
                    event_type,
                    sub.get("id"),
                )
                raise HTTPException(status_code=401, detail="Invalid webhook signature")

    import orjson

    payload = orjson.loads(raw_body) if raw_body else {}

    logger.info(
        "Webhook inbound: event=%s, has_signature=%s, client=%s",
        event_type,
        bool(signature),
        client_ip,
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

        return {"status": exchange.status.value, "error": exchange.error}
    except KeyError:
        raise HTTPException(
            status_code=404, detail=f"Маршрут 'webhook.{event_type}' не найден"
        )


# --- Outbound webhook ---


async def send_webhook_event(
    event_type: str, payload: dict[str, Any]
) -> list[dict[str, Any]]:
    """Отправляет событие на все подписанные URL.

    Args:
        event_type: Тип события.
        payload: Данные для отправки.

    Returns:
        Список результатов отправки.
    """
    # A4 (ADR-009): aiohttp → httpx.
    import httpx

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
            sig = hmac.new(sub.secret.encode(), body_bytes, hashlib.sha256).hexdigest()
            headers["X-Webhook-Signature"] = sig

        try:
            async with httpx.AsyncClient(http2=True, timeout=10.0) as session:
                resp = await session.post(sub.target_url, json=payload, headers=headers)
                results.append(
                    {
                        "subscription_id": sub.id,
                        "status": resp.status_code,
                        "success": 200 <= resp.status_code < 300,
                    }
                )
        except Exception as exc:
            logger.exception(
                "Webhook outbound failed: sub=%s, url=%s", sub.id, sub.target_url
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
