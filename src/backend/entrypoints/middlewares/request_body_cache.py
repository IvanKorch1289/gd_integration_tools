"""Request body cache middleware — однократное чтение тела запроса.

Назначение:
    FastAPI/Starlette кешируют тело запроса внутри `Request._body` при
    первом `await request.body()`, однако каждый последующий вызов всё
    равно затрагивает ASGI `receive` через `_receive` замыкание и копирует
    bytes. На цепочке из 3 middleware (`InnerRequestLoggingMiddleware`,
    `AuditReplayMiddleware`, `AuditLogMiddleware`) это даёт видимый overhead.

Решение:
    1. На входе один раз читаем `await request.body()` (bounded
       `max_body_size`, по умолчанию 10 МБ).
    2. Кладём bytes в `request.state.body`.
    3. Переопределяем `request._receive` замыканием, которое отдаёт
       cached body как single `http.request` message — прозрачно для
       всех downstream, которые продолжат вызывать `request.body()`
       / `request.json()` / `request.form()`.

Downstream middleware (audit_log, request_log, audit_replay) первым
делом проверяют `request.state.body` и только на graceful-fallback
вызывают `await request.body()`.

Фаза: IL-OBS1 (ADR-032).
"""

from __future__ import annotations

import logging

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp, Message

__all__ = ("RequestBodyCacheMiddleware",)

logger = logging.getLogger("infra.middleware.body_cache")

_DEFAULT_MAX_BODY_SIZE = 10 * 1024 * 1024  # 10 МБ safety limit
_BODYLESS_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "DELETE", "TRACE"})


class RequestBodyCacheMiddleware(BaseHTTPMiddleware):
    """Кеширует тело запроса в `request.state.body` ровно один раз.

    Поведение:
        * Для методов без тела (`GET`, `HEAD`, `OPTIONS`, `DELETE`, `TRACE`) —
          no-op.
        * Для тел размером `> max_body_size` — кеш не сохраняется,
          downstream читают поток напрямую (контракт FastAPI сохраняется).
        * Для остальных — читаем body, выставляем `request.state.body`,
          переопределяем `_receive` замыканием, возвращающим cached
          body как `http.request` message с `more_body=False`.

    Args:
        app: ASGI-приложение.
        max_body_size: Максимальный размер тела для кеширования (bytes).
    """

    def __init__(
        self, app: ASGIApp, *, max_body_size: int = _DEFAULT_MAX_BODY_SIZE
    ) -> None:
        super().__init__(app)
        self.max_body_size = max(0, int(max_body_size))

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Кеширует body (если применимо) и передаёт управление дальше.

        Args:
            request: Входящий HTTP-запрос.
            call_next: Следующий middleware/обработчик.

        Returns:
            HTTP-ответ без изменений.
        """
        if request.method in _BODYLESS_METHODS:
            return await call_next(request)

        # Пропускаем streaming/large uploads — не буферизуем.
        content_length = self._parse_content_length(request)
        if content_length is not None and content_length > self.max_body_size:
            logger.debug(
                "body_cache: skip body caching (content-length=%d > max=%d)",
                content_length,
                self.max_body_size,
            )
            return await call_next(request)

        try:
            body = await request.body()
        except Exception as exc:  # noqa: BLE001
            logger.debug("body_cache: failed to read body: %s", exc)
            return await call_next(request)

        if len(body) > self.max_body_size:
            # Тело уже прочитано, но превышает лимит — НЕ кешируем,
            # однако вернуть поток уже не сможем. Переопределяем receive,
            # чтобы endpoint-handler не повис на `request.body()`.
            logger.warning(
                "body_cache: body too large (%d > %d); caching disabled",
                len(body),
                self.max_body_size,
            )
            self._install_replay_receive(request, body)
            return await call_next(request)

        # Нормальный путь: кеш + replay receive для downstream.
        request.state.body = body
        self._install_replay_receive(request, body)

        return await call_next(request)

    @staticmethod
    def _parse_content_length(request: Request) -> int | None:
        """Парсит `Content-Length` заголовок; None если отсутствует/некорректен."""
        raw = request.headers.get("content-length")
        if raw is None:
            return None
        try:
            return int(raw)
        except TypeError, ValueError:
            return None

    @staticmethod
    def _install_replay_receive(request: Request, body: bytes) -> None:
        """Переопределяет `request._receive` так, чтобы он отдавал cached body.

        Первый вызов `receive()` вернёт `http.request` message с полным
        cached body и `more_body=False`. Последующие вызовы отдают
        `http.disconnect` (стандартный ASGI protocol).
        """
        delivered = {"done": False}

        async def _replay_receive() -> Message:
            if not delivered["done"]:
                delivered["done"] = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        # Starlette Request стор `_receive` как атрибут; переопределяем.
        try:
            request._receive = _replay_receive  # type: ignore[attr-defined]
        except Exception:  # pragma: no cover
            # Fallback: Starlette API изменился — ничего страшного, просто
            # downstream вторично прочитают тело.
            logger.debug("body_cache: cannot override request._receive")


def cached_body(request: Request) -> bytes | None:
    """Хелпер для downstream middleware: возвращает cached body или None.

    Использование::

        from src.backend.entrypoints.middlewares.request_body_cache import cached_body

        body = cached_body(request)
        if body is None:
            body = await request.body()

    Args:
        request: FastAPI Request.

    Returns:
        Cached body bytes или None, если кеша нет.
    """
    body = getattr(request.state, "body", None)
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return None
