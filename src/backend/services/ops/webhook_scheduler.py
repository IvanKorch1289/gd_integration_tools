"""Webhook Scheduler — планирование отправки webhooks по cron/delay.

v6 W3 / 25.09 audit: добавлена tenant isolation (ADR-0345 Option A).
Каждый webhook schedule хранится под tenant-prefixed Redis key
``webhook:scheduled:{tenant_id}:{schedule_id}``. ``get``/``cancel``/
``list_scheduled``/``execute_webhook`` требуют ``tenant_id`` и фильтруют
только по своему tenant namespace — кросс-tenant доступ запрещён.
"""

from __future__ import annotations

import uuid
from typing import Any

import orjson

from src.backend.core.di.app_state import app_state_singleton
from src.backend.core.di.providers import get_redis_kv_client_provider
from src.backend.core.logging import get_logger

__all__ = ("WebhookScheduler", "get_webhook_scheduler")

logger = get_logger(__name__)

_PREFIX = "webhook:scheduled"
_GLOBAL_TENANT = "__global__"  # marker для non-tenant (system) webhooks


def _tenant_key(tenant_id: str, schedule_id: str) -> str:
    """Build tenant-namespaced Redis key.

    Empty/None tenant → ``__global__`` namespace (для system webhooks).
    Per ADR-0345: user-data API требует non-empty tenant; global namespace
    только для legitimate system use-cases (admin, infra checks).
    """
    t = (tenant_id or "").strip() or _GLOBAL_TENANT
    return f"{_PREFIX}:{t}:{schedule_id}"


def _tenant_scan_pattern(tenant_id: str) -> str:
    """SCAN pattern для tenant-namespaced keys."""
    t = (tenant_id or "").strip() or _GLOBAL_TENANT
    return f"{_PREFIX}:{t}:*"


class WebhookScheduler:
    """Планирование исходящих webhooks с cron/delay.

    Tenant-scoped (v6 W3): все public методы принимают ``tenant_id`` и
    namespace Redis keys по tenant. Кросс-tenant lookup/get/cancel
    возвращает ``None`` / ``False`` без side-effects.
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
        *,
        tenant_id: str = "",
    ) -> str:
        """Планирует отправку webhook. Возвращает schedule_id.

        Args:
            tenant_id: Идентификатор тенанта-владельца. Обязателен для
                user-data webhook'ов (per ADR-0345). Пустая строка →
                global namespace (``__global__``); допустимо только для
                system/admin операций.
        """
        schedule_id = str(uuid.uuid4())[:8]
        effective_tenant = (tenant_id or "").strip() or _GLOBAL_TENANT

        task = {
            "id": schedule_id,
            "url": url,
            "payload": payload,
            "headers": headers or {},
            "cron": cron,
            "delay_seconds": delay_seconds,
            "status": "scheduled",
            "tenant_id": effective_tenant,
        }

        client = get_redis_kv_client_provider()
        key = _tenant_key(tenant_id, schedule_id)
        await client.set(key, orjson.dumps(task, default=str), ex=86400 * 7)

        logger.info(
            "Webhook scheduled: tenant=%s schedule_id=%s url=%s",
            effective_tenant,
            schedule_id,
            url,
        )
        return schedule_id

    async def cancel(self, schedule_id: str, *, tenant_id: str = "") -> bool:
        """Отменяет запланированный webhook (только для указанного tenant).

        Returns:
            ``True`` если webhook удалён; ``False`` если не найден в
            tenant namespace (включая кросс-tenant access).
        """
        client = get_redis_kv_client_provider()
        key = _tenant_key(tenant_id, schedule_id)
        deleted = await client.delete(key)
        if deleted:
            logger.info(
                "Webhook cancelled: tenant=%s schedule_id=%s",
                (tenant_id or "").strip() or _GLOBAL_TENANT,
                schedule_id,
            )
        return bool(deleted)

    async def list_scheduled(
        self, *, tenant_id: str = ""
    ) -> list[dict[str, Any]]:
        """Возвращает список запланированных webhooks для tenant.

        Tenant isolation: фильтрует только по namespace указанного tenant.
        Без tenant (пустая строка) → только global namespace.
        """
        client = get_redis_kv_client_provider()
        pattern = _tenant_scan_pattern(tenant_id)
        keys: list[str] = []
        async for key in client.scan_iter(pattern):
            keys.append(key)

        tasks: list[dict[str, Any]] = []
        for key in keys:
            raw = await client.get(key)
            if raw:
                tasks.append(orjson.loads(raw))
        return tasks

    async def get(
        self, schedule_id: str, *, tenant_id: str = ""
    ) -> dict[str, Any] | None:
        """Получает информацию о задаче в рамках tenant namespace.

        Returns:
            ``None`` если schedule не найден ИЛИ принадлежит другому tenant
            (кросс-tenant access запрещён per ADR-0345).
        """
        client = get_redis_kv_client_provider()
        key = _tenant_key(tenant_id, schedule_id)
        raw = await client.get(key)
        return orjson.loads(raw) if raw else None

    async def execute_webhook(
        self, schedule_id: str, *, tenant_id: str = ""
    ) -> dict[str, Any]:
        """Выполняет webhook немедленно (tenant-scoped).

        Security: URL валидируется через _validate_url() для защиты от SSRF
        (блокирует private IPs, localhost, cloud metadata endpoints).
        Cross-tenant lookup → ``{"error": "not_found"}``.
        """
        task = await self.get(schedule_id, tenant_id=tenant_id)
        if not task:
            return {"error": "not_found"}

        # SSRF protection — reuse validator from scraping processors
        from src.backend.dsl.engine.processors.scraping import _validate_url

        try:
            _validate_url(task["url"])
        except ValueError as exc:
            logger.warning("Webhook SSRF blocked: %s — %s", schedule_id, exc)
            return {
                "schedule_id": schedule_id,
                "error": f"URL blocked (SSRF protection): {exc}",
                "success": False,
            }

        from src.backend.core.config.features import feature_flags
        from src.backend.core.net.migration_helper import make_http_client
        from src.backend.core.resilience.rpa_policy import (
            RPACallExhausted,
            get_rpa_policy,
        )

        async def _do_post() -> Any:
            async with make_http_client(
                timeout=30, plugin="webhook_scheduler"
            ) as client:
                resp = await client.post(
                    task["url"], json=task["payload"], headers=task.get("headers", {})
                )
            import httpx

            if 500 <= resp.status_code < 600:
                raise httpx.HTTPStatusError(
                    f"upstream 5xx: {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            return resp

        policy = (
            get_rpa_policy()
            if feature_flags.webhook_resilience_policy_enabled
            else None
        )
        try:
            if policy is not None:
                response = await policy.call(
                    _do_post, transport="webhook", route_id=schedule_id, payload=task
                )
            else:
                response = await _do_post()
        except RPACallExhausted as exhausted:
            logger.warning(
                "Webhook %s exhausted retries: %s", schedule_id, exhausted.last_error
            )
            return {
                "schedule_id": schedule_id,
                "success": False,
                "error": "retries_exhausted",
            }

        result = {
            "schedule_id": schedule_id,
            "status_code": response.status_code,
            "success": response.is_success,
        }
        logger.info("Webhook executed: %s -> %d", schedule_id, response.status_code)
        return result


@app_state_singleton("webhook_scheduler", factory=WebhookScheduler)
def get_webhook_scheduler() -> WebhookScheduler:
    """Фабрика: WebhookSchedulerService."""
    raise NotImplementedError  # заменяется декоратором
