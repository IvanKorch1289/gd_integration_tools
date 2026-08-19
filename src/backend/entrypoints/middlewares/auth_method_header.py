"""Middleware, добавляющий header ``X-Auth-Method`` в response (cycle 37).

Полезно клиентам и observability: сразу видно, каким способом
запрос был аутентифицирован (api_key/jwt/express_jwt/...).

Метод считывается из ``scope['state']['auth']`` (выставляется
``require_auth`` в ``auth_selector.py``). Если auth-контекст не
найден — header не добавляется.

Cycle 37: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с другими middleware (cycle 33 L1
SecurityHeaders, cycle 36 RequestIDMiddleware).

S191 fix: по умолчанию middleware ВЫКЛЮЧЕН — header leaks auth
method (information disclosure для attackers — позволяет probe
endpoints для определения auth scheme). Включение через явное
``enabled=True`` в конструкторе.
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ("AuthMethodHeaderMiddleware",)


class AuthMethodHeaderMiddleware:
    """Pure ASGI middleware для X-Auth-Method header (S191 security default).

    Поведение:
    - Если ``enabled=False`` (default): header НЕ emit'ится (security).
    - Если ``enabled=True``: читает ``scope['state']['auth'].method`` и
      добавляет ``X-Auth-Method=<method>`` в response headers.

    Pure ASGI: header добавляется в ``http.response.start`` через
    send-wrapper — гарантирует корректное применение до любого body
    chunk и для streaming/SSE responses.

    Cycle 37 retrospective: auth context устанавливается
    downstream-приложением (auth middleware пишет в ``scope['state']``
    ПОСЛЕ того, как наш __call__ уже отработал). Поэтому header value
    вычисляется INSIDE send-wrapper (после downstream), а не в __call__.
    """

    def __init__(
        self, app: ASGIApp, header_name: str = "X-Auth-Method", enabled: bool = False
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            header_name: Имя response header.
            enabled: Включить emit header (default: False для security).

        """
        self.app = app
        self._header_name = header_name
        self._enabled = enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без изменений.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        if not self._enabled:
            # Нечего добавлять — пробрасываем downstream без обёртки.
            await self.app(scope, receive, send)
            return

        # Wrap send — header value читается из scope['state']['auth']
        # ВНУТРИ wrapper (после того, как auth middleware заполнил state).
        send_wrapper = _make_send_wrapper(send, scope, self._header_name)
        await self.app(scope, receive, send_wrapper)

    @staticmethod
    def _extract_method_value(scope: Scope) -> bytes | None:
        """Извлекает auth method из scope['state']['auth'] (cycle 37 helper).

        Pure ASGI scope['state'] — это dict, модифицируемый
        downstream middleware (auth_selector пишет state['auth']
        ПОСЛЕ нашего __call__). Возвращает encoded header value
        или None если auth context не установлен.
        """
        state = scope.get("state", {})
        ctx = state.get("auth") if isinstance(state, dict) else None
        method = getattr(ctx, "method", None)
        if method is None:
            return None
        value = getattr(method, "value", str(method))
        return value.encode("latin-1")


def _make_send_wrapper(send: Send, scope: Scope, header_name: str) -> Send:
    """Создаёт обёртку вокруг ``send``, добавляющую header в start message.

    Header value вычисляется через :meth:`AuthMethodHeaderMiddleware._extract_method_value`
    ВНУТРИ wrapper (после того, как downstream заполнил ``scope['state']``).
    Если resolver возвращает None (auth context not set) — header
    НЕ добавляется (preserves old behavior).

    Header добавляется только в ``http.response.start`` сообщение
    (где это валидно по ASGI-спецификации). Если downstream уже
    послал такой header — мы перезаписываем (наш auth source of truth).
    """
    header_name_bytes = header_name.lower().encode("latin-1")

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            header_value = AuthMethodHeaderMiddleware._extract_method_value(scope)
            if header_value is not None:
                existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
                existing = [
                    (k, v) for k, v in existing if k.lower() != header_name_bytes
                ]
                existing.append((header_name_bytes, header_value))
                message["headers"] = existing
        await send(message)

    return send_wrapper
