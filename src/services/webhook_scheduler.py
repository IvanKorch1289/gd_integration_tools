"""Webhook Scheduler — планирование отправки webhooks по cron/delay."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from app.core.decorators.singleton import singleton
from app.infrastructure.clients.redis import redis_client

__all__ = ("WebhookScheduler", "get_webhook_scheduler")

logger = logging.getLogger(__name__)

_PREFIX = "webhook:scheduled"


@singleton
class WebhookScheduler:
    """Планирование исходящих webhooks с cron/delay.

    Хранит задачи в Redis, выполняет через APScheduler.
    """

    def __init__(self) -> None:
        self._scheduler: Any = None

    async def schedule(
        self,
        url: str,
        payload: dict[str, Any],
        cron: str | None = None,
        delay_seconds: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> str:
        """Планирует отправку webhook. Возвращает schedule_id."""
        schedule_id = str(uuid.uuid4())[:8]

        task = {
            "id": schedule_id,
            "url": url,
            "payload": payload,
            "headers": headers or {},
            "cron": cron,
            "delay_seconds": delay_seconds,
            "status": "scheduled",
        }

        key = f"{_PREFIX}:{schedule_id}"
        await redis_client.client.set(
            key,
            json.dumps(task, default=str),
            ex=86400 * 7,
        )

        logger.info("Webhook scheduled: %s -> %s", schedule_id, url)
        return schedule_id

    async def cancel(self, schedule_id: str) -> bool:
        """Отменяет запланированный webhook."""
        key = f"{_PREFIX}:{schedule_id}"
        deleted = await redis_client.client.delete(key)
        if deleted:
            logger.info("Webhook cancelled: %s", schedule_id)
        return bool(deleted)

    async def list_scheduled(self) -> list[dict[str, Any]]:
        """Возвращает список запланированных webhooks."""
        keys = []
        async for key in redis_client.client.scan_iter(f"{_PREFIX}:*"):
            keys.append(key)

        tasks = []
        for key in keys:
            raw = await redis_client.client.get(key)
            if raw:
                tasks.append(json.loads(raw))
        return tasks

    async def get(self, schedule_id: str) -> dict[str, Any] | None:
        """Получает информацию о задаче."""
        key = f"{_PREFIX}:{schedule_id}"
        raw = await redis_client.client.get(key)
        return json.loads(raw) if raw else None

    async def execute_webhook(self, schedule_id: str) -> dict[str, Any]:
        """Выполняет webhook немедленно.

        Security: URL валидируется через _validate_url() для защиты от SSRF
        (блокирует private IPs, localhost, cloud metadata endpoints).
        """
        task = await self.get(schedule_id)
        if not task:
            return {"error": "not_found"}

        # SSRF protection — reuse validator from scraping processors
        from app.dsl.engine.processors.scraping import _validate_url
        try:
            _validate_url(task["url"])
        except ValueError as exc:
            logger.warning("Webhook SSRF blocked: %s — %s", schedule_id, exc)
            return {
                "schedule_id": schedule_id,
                "error": f"URL blocked (SSRF protection): {exc}",
                "success": False,
            }

        import httpx

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                task["url"],
                json=task["payload"],
                headers=task.get("headers", {}),
            )
            result = {
                "schedule_id": schedule_id,
                "status_code": response.status_code,
                "success": response.is_success,
            }
            logger.info("Webhook executed: %s -> %d", schedule_id, response.status_code)
            return result


def get_webhook_scheduler() -> WebhookScheduler:
    return WebhookScheduler()
