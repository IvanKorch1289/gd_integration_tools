"""Tenant middleware — извлекает tenant_id из запроса (cycle 38, pure ASGI).

Wave 6.5a: ``set_correlation_context`` резолвится через DI provider
(``core.di.providers.get_correlation_context_setter_provider``), что
снимает entrypoints → infrastructure layer-violation.

Cycle 38: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с другими middleware (cycle 33 L1
SecurityHeaders, cycle 36 RequestID, cycle 37 AuthMethodHeader).

Порядок приоритета tenant_id:
1. Header ``X-Tenant-ID``
2. ``scope['state']['tenant_id']`` (если auth middleware уже отработал)
3. ``default_tenant`` constructor arg
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.di.providers import get_correlation_context_setter_provider

__all__ = ("TenantMiddleware",)

_TENANT_HEADER = "X-Tenant-ID"
_TENANT_HEADER_BYTES = _TENANT_HEADER.lower().encode("latin-1")


class TenantMiddleware:
    """Pure ASGI middleware для multi-tenant isolation.

    Делает:
    1. Извлекает ``tenant_id`` из request (header → scope.state.tenant_id
       → default).
    2. Устанавливает ``scope['state']['tenant_id']`` (доступно downstream
       как ``request.state.tenant_id``).
    3. Вызывает ``set_correlation_context(tenant_id=...)`` для
       propagation в structlog (все лог-события содержат tenant_id).
    4. Добавляет ``X-Tenant-ID`` в response headers (через send-wrapper).
    """

    def __init__(self, app: ASGIApp, default_tenant: str = "default") -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            default_tenant: tenant_id если header и state пусты.

        """
        self.app = app
        self._default = default_tenant

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без модификации state.

        Cycle 38 retrospective: tenant_id resolution делается
        INSIDE send-wrapper, а не в __call__ — потому что inner
        auth middleware может установить ``state['tenant_id']``
        ПОСЛЕ того, как наш __call__ уже отработал (ASGI outer-to-inner
        ordering). Этот же lesson был в cycle 37 AuthMethodHeader.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Wrap send — header extraction, state-merge, default-fallback
        # ВСЁ происходит в _resolve_tenant_id внутри send-wrapper.
        # Мы НЕ pre-fill state['tenant_id'] здесь чтобы не перезаписать
        # значение, которое inner auth middleware установит позже.
        send_wrapper = _make_send_wrapper(send, scope, self._default)
        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _resolve_tenant_id(scope: Scope, default_tenant: str) -> str:
        """Резолвит tenant_id с приоритетом: header > state > default.

        Вызывается INSIDE send-wrapper (cycle 38 retrospective) —
        после того, как inner auth middleware установил
        ``state['tenant_id']``. Возвращает:
        1. Header ``X-Tenant-ID`` (highest priority)
        2. ``scope['state']['tenant_id']`` (auth middleware)
        3. ``default_tenant`` (fallback)
        """
        header_value = _get_header(scope, _TENANT_HEADER_BYTES)
        if header_value:
            return header_value
        state = scope.get("state", {})
        if isinstance(state, dict):
            state_tenant = state.get("tenant_id")
            if isinstance(state_tenant, str):
                return state_tenant
        return default_tenant


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Извлекает header из ASGI scope по lowercase bytes-имени.

    Returns:
        Header value (str) или None если не найден.

    """
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


def _make_send_wrapper(send: Send, scope: Scope, default_tenant: str) -> Send:
    """Создаёт обёртку вокруг ``send``, добавляющую X-Tenant-ID в start.

    Header добавляется только в ``http.response.start`` сообщение.
    Если downstream уже послал X-Tenant-ID — мы перезаписываем
    (наш tenant source of truth).

    Cycle 38: tenant_id резолвится INSIDE wrapper через
    :meth:`TenantMiddleware._resolve_tenant_id` (после того, как
    inner auth middleware установил state['tenant_id']).

    Также вызывает ``set_correlation_context(tenant_id=...)`` для
    structlog propagation — здесь это безопасно (после __call__ —
    не блокирует request path, только logging payload).
    """

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            tenant_id = TenantMiddleware._resolve_tenant_id(scope, default_tenant)
            tenant_id_bytes = tenant_id.encode("latin-1")

            existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            existing = [
                (k, v) for k, v in existing if k.lower() != _TENANT_HEADER_BYTES
            ]
            existing.append((_TENANT_HEADER_BYTES, tenant_id_bytes))
            message["headers"] = existing

            # ContextVar для structlog (только после resolve, чтобы
            # не перезаписать если inner auth middleware ещё не
            # отработал — впрочем, к этому моменту send уже вызван,
            # значит все middlewares отработали).
            try:
                get_correlation_context_setter_provider()(tenant_id=tenant_id)
            except (
                ImportError,
                AttributeError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as corr_exc:
                # cycle-9/D-AUDIT-1001: narrow exceptions + observability.
                # ImportError — provider missing, AttributeError — API
                # change, RuntimeError — DI unavailable, TypeError —
                # wrong tenant_id, ValueError — invalid tenant_id.
                import logging

                logging.getLogger(__name__).debug(
                    "tenant_middleware.correlation_setter_failed",
                    extra={"tenant_id": tenant_id, "error": str(corr_exc)},
                )
        await send(message)

    return send_wrapper
