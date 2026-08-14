"""Request body cache middleware — однократное чтение тела запроса (cycle 52 pure ASGI).

Назначение:
    FastAPI/Starlette кешируют тело запроса внутри `Request._body` при
    первом `await request.body()`, однако каждый последующий вызов всё
    равно затрагивает ASGI `receive` через `_receive` замыкание и копирует
    bytes. На цепочке из 3 middleware (`InnerRequestLoggingMiddleware`,
    `AuditReplayMiddleware`, `AuditLogMiddleware`) это даёт видимый overhead.

Решение:
    1. На входе один раз читаем body через receive() chunks (bounded
       `max_body_size`, по умолчанию 10 МБ).
    2. Кладём bytes в ``scope['state']['body']`` (cycle 52: pure ASGI
       compatible — downstream читает через ``state.get('body')``).
    3. Replay receive closure возвращает cached body как single
       ``http.request`` message — прозрачно для всех downstream, которые
       продолжат вызывать receive().

Downstream middleware (audit_log, request_log, audit_replay) первым
делом проверяют ``state.get('body')`` и только на graceful-fallback
вызывают receive().

Фаза: IL-OBS1 (ADR-032).
"""

from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.logging import get_logger

__all__ = ("RequestBodyCacheMiddleware", "cached_body")

logger = get_logger("infra.middleware.body_cache")

_DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 МБ safety limit
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"})


def cached_body(scope: Scope) -> bytes | None:
    """Извлекает cached body из ASGI scope state (cycle 52 helper).

    Args:
        scope: ASGI scope.

    Returns:
        Cached body bytes или None если не закэшировано.

    """
    state = scope.get("state", {}) if "state" in scope else {}
    if not isinstance(state, dict):
        return None
    body = state.get("body")
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return None


class RequestBodyCacheMiddleware:
    """Кеширует тело запроса в scope['state']['body'] ровно один раз (cycle 52).

    Поведение:
        * Для методов без тела (`GET`, `HEAD`, `OPTIONS`, `DELETE`, `TRACE`) —
          no-op.
        * Для тел размером `> max_body_size` — кеш не сохраняется,
          downstream читают поток напрямую.
        * Для остальных — читаем body, выставляем в state['body'],
          переопределяем receive замыканием, возвращающим cached body
          как `http.request` message с `more_body=False`.

    Args:
        app: ASGI-приложение.
        max_body_size: Максимальный размер тела для кеширования (bytes).

    """

    def __init__(
        self, app: ASGIApp, *, max_body_size: int = _DEFAULT_MAX_BODY_SIZE,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            max_body_size: Максимальный размер тела для кеширования.

        """
        self.app = app
        self.max_body_size = max(0, int(max_body_size))

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Кеширует body (если применимо) и передаёт управление дальше.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            # Non-HTTP scope (websocket/lifespan) — no body caching.
            await self.app(scope, receive, send)
            return

        method = scope.get("method", "")

        # Bodyless methods skip caching.
        if method in _BODYLESS_METHODS:
            await self.app(scope, receive, send)
            return

        # Пропускаем streaming/large uploads — не буферизуем.
        content_length = self._parse_content_length(scope)
        if content_length is not None and content_length > self.max_body_size:
            logger.debug(
                "body_cache: skip body caching (content-length=%d > max=%d)",
                content_length,
                self.max_body_size,
            )
            await self.app(scope, receive, send)
            return

        # Читаем body chunks (cycle 52: pure ASGI receive() loop).
        try:
            body = await self._read_body(receive)
        except Exception as exc:
            logger.debug("body_cache: failed to read body: %s", exc)
            await self.app(scope, receive, send)
            return

        if len(body) > self.max_body_size:
            # Тело уже прочитано, но превышает лимит — НЕ кешируем,
            # однако вернуть поток уже не сможем. Переопределяем receive,
            # чтобы endpoint-handler не повис на receive().
            logger.warning(
                "body_cache: body too large (%d > %d); caching disabled",
                len(body),
                self.max_body_size,
            )
            replay_receive = self._install_replay_receive(scope, receive, body)
            # 2026-08-14 fix (Task 4 unblock): downstream ДОЛЖЕН получать
            # replay_receive, не consumed original (см. нормальный путь ниже).
            await self.app(scope, replay_receive, send)
            return

        # Нормальный путь: кеш + replay receive для downstream.
        if "state" not in scope:
            scope["state"] = {}
        scope["state"]["body"] = body
        replay_receive = self._install_replay_receive(scope, receive, body)

        # 2026-08-14 fix (Task 4 unblock): downstream ДОЛЖЕН получать
        # replay_receive, не consumed original — иначе FastAPI body-parser
        # (``fastapi/routing.py:451`` JSON-decode) hangs 30 сек и
        # возвращает ``400 "There was an error parsing the body"``.
        await self.app(scope, replay_receive, send)

    @staticmethod
    async def _read_body(receive: Receive) -> bytes:
        """Читает body chunks через receive() (cycle 52 helper)."""
        body_chunks: list[bytes] = []
        more_body = True
        while more_body:
            message = await receive()
            if message["type"] == "http.disconnect":
                break
            body_chunks.append(message.get("body", b""))
            more_body = message.get("more_body", False)
        return b"".join(body_chunks)

    @staticmethod
    def _parse_content_length(scope: Scope) -> int | None:
        """Парсит `Content-Length` заголовок из ASGI scope.

        Returns:
            int или None если отсутствует/некорректен.

        """
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"content-length":
                try:
                    return int(header_value.decode("latin-1"))
                except (TypeError, ValueError):
                    return None
        return None

    @staticmethod
    def _install_replay_receive(
        scope: Scope, original_receive: Receive, body: bytes,
    ) -> Receive:
        """Устанавливает replay receive в scope для downstream (cycle 52).

        First receive() returns http.request with cached body,
        subsequent return http.disconnect (ASGI protocol).

        2026-08-14 fix (Task 4 unblock): возвращает replay_receive
        callable, который caller ДОЛЖЕН передать в ``self.app(scope,
        replay_receive, send)``. Без этого downstream FastAPI
        body-parser получает consumed original_receive →
        ``await receive()`` hangs 30 сек → ``400 "There was an error
        parsing the body"`` (см. fastapi/routing.py:471).
        Также сохраняет ``scope["original_receive"]`` для downstream,
        которым нужен raw channel.
        """
        delivered = {"done": False}

        async def replay_receive() -> Message:
            if not delivered["done"]:
                delivered["done"] = True
                return {
                    "type": "http.request",
                    "body": body,
                    "more_body": False,
                }
            return {"type": "http.disconnect"}

        # Pre-fix bug: ``scope["receive"] = original_receive`` —
        # downstream FastAPI body-parser получал consumed channel и
        # hangs. Теперь downstream получает replay_receive.
        scope["receive"] = replay_receive
        scope["original_receive"] = original_receive  # для downstream, нужен raw channel
        return replay_receive
