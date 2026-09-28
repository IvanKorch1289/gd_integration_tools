"""Security headers middleware (pure ASGI).

S176 cycle 33 B-07 fix: previous implementation inherited from
:class:`starlette.middleware.base.BaseHTTPMiddleware`, который запускает
``dispatch()`` в отдельной task и буферизует streaming-ответы целиком
перед отправкой клиенту. Это создаёт race condition между
``call_next(request)`` и реальной отправкой headers клиенту, а также
ломает Server-Sent Events / WebSocket-upgrade, потому что весь стрим
накапливается в памяти до полного завершения downstream-цепочки.

Pure ASGI-вариант перехватывает сообщение ``http.response.start``
через обёртку вокруг ``send`` и инжектирует security-заголовки ровно
в тот момент, когда downstream публикует стартовую строку. Это
гарантирует:

* headers применяются ко всем response-формам (включая streaming,
  chunked, и WebSocket-upgrade с custom статусом);
* нет буферизации body (память O(1) на request);
* отсутствует race между ``call_next`` и реальной отправкой;
* non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
  без изменений.

Public API сохранён: ``SecurityHeadersMiddleware(app)`` и
набор инжектируемых заголовков идентичны pre-fix-варианту.
"""

from __future__ import annotations

from collections.abc import Iterable

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ("SecurityHeadersMiddleware",)


# Список (header-name, header-value) байтовыми парами для прямой
# вставки в ASGI-headers-list. Имена lowercase по ASGI-спецификации.
_SECURITY_HEADERS: tuple[tuple[bytes, bytes], ...] = (
    (b"strict-transport-security", b"max-age=63072000; includeSubDomains"),
    (b"x-content-type-options", b"nosniff"),
    (b"x-frame-options", b"DENY"),
    (b"content-security-policy", b"default-src 'self'"),
    (b"permissions-policy", b"geolocation=(), microphone=()"),
)

# Множество имён для фильтрации conflicting headers от downstream-приложения:
# наши security-заголовки всегда должны выигрывать (override).
_SECURITY_HEADER_NAMES: frozenset[bytes] = frozenset(
    name for name, _ in _SECURITY_HEADERS
)

# Документация API требует отдельной CSP.
#
# Найдено браузерной проверкой (Playwright, HEAD bbadf108a): /docs и /redoc
# отдавали HTTP 200, но страница оставалась пустой. Причина — тот же
# ``default-src 'self'``: FastAPI подключает Swagger UI и ReDoc с
# ``cdn.jsdelivr.net`` и выполняет inline-скрипты, поэтому браузер блокировал
# и стили, и скрипты:
#
#   Loading the script 'https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/
#   swagger-ui-bundle.js' violates ... "default-src 'self'". Blocked.
#
# Из-за этого интерактивная документация не работала — и именно поэтому
# отсутствие securitySchemes в спецификации никого не насторожило: страницу
# никто не видел.
#
# Послабление применяется ТОЛЬКО к публичным HTML-страницам документации.
# JSON-ответы API, в том числе /openapi.json, сохраняют строгую политику.
# Домен в allowlist — ровно тот, что подставляет FastAPI.
_DOCS_PATH_PREFIXES: tuple[str, ...] = ("/docs", "/redoc")

_DOCS_CSP: tuple[tuple[bytes, bytes], ...] = (
    *(
        (name, value)
        for name, value in _SECURITY_HEADERS
        if name != b"content-security-policy"
    ),
    (
        b"content-security-policy",
        # Origins сняты с реально отдаваемых /docs и /redoc, а не угаданы:
        #   cdn.jsdelivr.net     — swagger-ui-dist@5 (js+css) и redoc standalone.js
        #   fastapi.tiangolo.com — favicon, подставляемый FastAPI
        #   fonts.googleapis.com — шрифты ReDoc
        #   cdn.redoc.ly         — логотип ReDoc
        #   blob:                — web-worker, который ReDoc поднимает для рендера
        # Первый вариант политики запрещал worker-src и шрифты: консоль
        # браузера показывала 3 нарушения CSP и ReDoc отображался не полностью.
        b"default-src 'self'; "
        b"script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net blob:; "
        b"style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net "
        b"https://fonts.googleapis.com; "
        b"img-src 'self' data: https://fastapi.tiangolo.com https://cdn.redoc.ly; "
        b"font-src 'self' data: https://fonts.gstatic.com; "
        b"worker-src 'self' blob:; "
        b"connect-src 'self'",
    ),
)


def _headers_for(path: str) -> tuple[tuple[bytes, bytes], ...]:
    """Возвращает набор security-заголовков для указанного пути."""
    if any(path == p or path.startswith(f"{p}/") for p in _DOCS_PATH_PREFIXES):
        return _DOCS_CSP
    return _SECURITY_HEADERS


class SecurityHeadersMiddleware:
    """Pure ASGI middleware для добавления HTTP-заголовков безопасности.

    Перехватывает ``http.response.start`` и дописывает
    :data:`_SECURITY_HEADERS` в headers исходящего сообщения, гарантируя
    применение security-политики к каждому HTTP-ответу — включая
    streaming, chunked, error-responses и WebSocket-upgrade.

    Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
    downstream-приложению без изменений.

    Аргументы:
        app (ASGIApp): Inner ASGI-приложение (FastAPI/Starlette).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Для ``http`` scope оборачивает ``send`` так, чтобы в
        ``http.response.start`` наши security-заголовки были добавлены
        (и перезаписали conflicting значения от downstream). Для
        остальных scope (``websocket`` / ``lifespan``) — пробрасывает
        без изменений.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        send_wrapper = _make_send_wrapper(send, scope)
        await self.app(scope, receive, send_wrapper)


def _make_send_wrapper(send: Send, scope: Scope) -> Send:
    """Создаёт обёртку вокруг ``send``, инжектирующую security-заголовки.

    Создаётся как :func:`callable` (а не :meth:`__call__` класса) для
    краткости и zero-overhead per-request: одна замыкающая функция
    вместо объекта с bound-method. Иммутабельный capture ``_SECURITY_HEADERS``
    делает функцию безопасной для concurrent reuse на разных запросах.
    """
    path: str = scope.get("path", "")
    headers_to_inject: tuple[tuple[bytes, bytes], ...] = _headers_for(path)
    names_to_override: frozenset[bytes] = frozenset(
        name for name, _ in headers_to_inject
    )

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            existing: Iterable[tuple[bytes, bytes]] = message.get("headers", [])
            # Сохраняем downstream-заголовки, кроме тех, что мы переопределяем.
            filtered = [(k, v) for k, v in existing if k not in names_to_override]
            filtered.extend(headers_to_inject)
            message["headers"] = filtered
        await send(message)

    return send_wrapper
