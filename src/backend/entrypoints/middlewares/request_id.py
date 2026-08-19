"""Middleware для Request ID и Correlation ID (cycle 36 — pure ASGI).

Обеспечивает сквозную трассировку запросов через все
протоколы и компоненты системы.

- **X-Request-ID**: уникальный идентификатор конкретного
  HTTP-запроса (генерируется на входе, если не передан).
- **X-Correlation-ID**: идентификатор цепочки вызовов
  (пробрасывается между сервисами, генерируется если
  отсутствует).

Cycle 36 fix: переписано с ``BaseHTTPMiddleware`` на pure ASGI.
Преимущества:
- O(1) памяти на запрос (не буферизует body).
- Корректная работа со streaming/chunked/WebSocket-upgrade.
- Нет race condition между ``call_next`` и реальной отправкой
  headers клиенту (BaseHTTPMiddleware известен этим багом).
- Headers добавляются в ``http.response.start`` — до первого
  body chunk, до SSE-flush, до WS-upgrade.

Public API сохранён: ``RequestIDMiddleware(app)`` — drop-in
replacement.
"""

from __future__ import annotations

from uuid import uuid4

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ("RequestIDMiddleware",)


class RequestIDMiddleware:
    """Pure ASGI middleware для X-Request-ID и X-Correlation-ID.

    Поведение:
    1. На входе читает ``X-Request-ID`` и ``X-Correlation-ID`` из
       headers (если есть). Если отсутствуют — генерирует новые.
    2. Сохраняет оба ID в ``scope['state']`` (доступно downstream
       как ``request.state.request_id`` / ``request.state.correlation_id``).
    3. Перехватывает ``http.response.start`` и добавляет оба ID
       в response headers.

    Args:
        app: Inner ASGI-приложение.

    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без изменений — этот middleware
        специфичен для HTTP tracing.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Extract incoming headers (case-insensitive lookup).
        request_id = _get_header(scope, b"x-request-id") or _generate_id()
        correlation_id = _get_header(scope, b"x-correlation-id") or _generate_id()

        # Store в scope['state'] для downstream handlers
        # (FastAPI ``request.state.request_id`` алиасится на этот dict).
        if "state" not in scope:
            scope["state"] = {}
        state = scope["state"]
        state["request_id"] = request_id
        state["correlation_id"] = correlation_id

        send_wrapper = _make_send_wrapper(send, request_id, correlation_id)
        await self.app(scope, receive, send_wrapper)


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


def _make_send_wrapper(send: Send, request_id: str, correlation_id: str) -> Send:
    """Создаёт обёртку вокруг ``send``, инжектирующую tracing headers.

    Headers добавляются только в ``http.response.start`` сообщение
    (где это валидно по ASGI-спецификации). Body-сообщения
    пробрасываются без изменений.
    """
    # Pre-compute header tuples для скорости.
    request_id_header: tuple[bytes, bytes] = (
        b"x-request-id",
        request_id.encode("latin-1"),
    )
    correlation_id_header: tuple[bytes, bytes] = (
        b"x-correlation-id",
        correlation_id.encode("latin-1"),
    )

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            # Удаляем potential existing headers (defensive: client may have
            # sent через downstream middleware, но upstream клиент не мог).
            existing = [
                (k, v)
                for k, v in existing
                if k not in (b"x-request-id", b"x-correlation-id")
            ]
            existing.append(request_id_header)
            existing.append(correlation_id_header)
            message["headers"] = existing
        await send(message)

    return send_wrapper


def _generate_id() -> str:
    """Генерирует UUID4 hex (32 символа)."""
    return uuid4().hex
