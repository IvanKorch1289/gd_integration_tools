"""QuotaPolicy + QuotaCheckMiddleware — auth-level per-tenant квоты (Sprint 7 K1).

Назначение:
    Тонкий ASGI-middleware и Policy-объект, проверяющий per-tenant rpm/rpd
    лимиты ДО роутера. Все обращения к ``QuotasService`` идут только при
    включённом feature_flag ``per_tenant_billing_enabled`` — при OFF
    middleware превращается в passthrough.

Контракт:
    QuotaPolicy.tenant_extractor — callable, извлекающий tenant_id из
    request scope (по умолчанию читает заголовок ``X-Tenant-Id``).

    При превышении лимита middleware возвращает 429 Too Many Requests с
    JSON-телом ``{"detail": "...", "reset_at": <unix>}``.

    Middleware совместим с обычным ASGI3 интерфейсом (без зависимости от
    Starlette/FastAPI) — используется как чистый ASGI-уровень.
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from src.backend.core.auth.quotas_protocol import QuotaCheckResult, QuotasBackend

__all__ = ("QuotaCheckMiddleware", "QuotaPolicy", "default_tenant_extractor")

# ASGI-типы (без импорта тяжёлых stub'ов).
Scope = dict[str, Any]
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]
ASGIApp = Callable[[Scope, Receive, Send], Awaitable[None]]


def default_tenant_extractor(scope: Scope) -> str | None:
    """Извлекает tenant_id из ASGI scope (X-Tenant-Id header).

    Args:
        scope: ASGI scope dict.

    Returns:
        Значение X-Tenant-Id или None, если заголовок отсутствует.
    """
    if scope.get("type") != "http":
        return None
    headers = scope.get("headers") or []
    for name, value in headers:
        if name == b"x-tenant-id":
            try:
                return value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


@dataclass(frozen=True, slots=True)
class QuotaPolicy:
    """Декларативная политика проверки квот.

    Attributes:
        service: Экземпляр :class:`QuotasService`.
        tenant_extractor: callable(scope) → tenant_id (или None).
        skip_paths: Список path-префиксов, для которых проверка пропускается
            (health/metrics).
    """

    service: QuotasBackend
    tenant_extractor: Callable[[Scope], str | None] = default_tenant_extractor
    skip_paths: tuple[str, ...] = ("/health", "/metrics", "/api/v1/health")

    def should_skip(self, scope: Scope) -> bool:
        """True, если path попадает в skip_paths.

        Args:
            scope: ASGI scope.

        Returns:
            True если запрос исключён из проверки квоты.
        """
        path = scope.get("path", "") or ""
        return any(path.startswith(prefix) for prefix in self.skip_paths)

    async def check(self, tenant_id: str) -> QuotaCheckResult:
        """Регистрирует один запрос tenant и проверяет лимиты rpm/rpd.

        Args:
            tenant_id: Идентификатор арендатора.

        Returns:
            QuotaCheckResult.
        """
        return await self.service.consume_request(tenant_id)


class QuotaCheckMiddleware:
    """ASGI middleware — отказывает в обслуживании при превышении квоты.

    Args:
        app: Внутренний ASGI app.
        policy: :class:`QuotaPolicy` с настроенным QuotasService.

    Поведение:
        - non-HTTP scope → passthrough;
        - skip_paths → passthrough;
        - tenant_id отсутствует → passthrough (auth-middleware обязан был
          его проставить раньше);
        - QuotaCheckResult.allowed=False → ответ 429 без вызова app.
    """

    def __init__(self, app: ASGIApp, policy: QuotaPolicy) -> None:
        """Инициализирует middleware с указанной политикой."""
        self.app = app
        self.policy = policy

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """ASGI3 entrypoint — проверяет квоту и передаёт управление дальше."""
        if scope.get("type") != "http" or self.policy.should_skip(scope):
            await self.app(scope, receive, send)
            return
        tenant_id = self.policy.tenant_extractor(scope)
        if not tenant_id:
            await self.app(scope, receive, send)
            return
        result = await self.policy.check(tenant_id)
        if result.allowed:
            await self.app(scope, receive, send)
            return
        await self._send_429(send, result)

    @staticmethod
    async def _send_429(send: Send, result: QuotaCheckResult) -> None:
        """Отправляет HTTP 429 Too Many Requests с JSON-телом."""
        payload = {
            "detail": "quota_exceeded",
            "reason": result.reason,
            "reset_minute_at": result.usage.reset_minute_at,
            "reset_day_at": result.usage.reset_day_at,
        }
        body = json.dumps(payload).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": 429,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"retry-after", str(60).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
