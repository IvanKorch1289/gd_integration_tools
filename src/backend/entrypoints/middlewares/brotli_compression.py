"""BrotliCompressionMiddleware (Sprint 10 K2 W2, PERF-6.6).

ASGI-middleware: добавляет Brotli compression для response body, если
клиент поддерживает (``Accept-Encoding: br`` в request). Цель — снизить
JSON traffic ~60% (Brotli vs GZIP +20-30% при quality=4).

Поведение:

* активируется, если ``settings.app.compression_brotli == True``;
* срабатывает только для ответов c ``Content-Type: application/json``
  (или ``application/*+json``) и размером ≥ ``brotli_minimum_size``;
* в response добавляются заголовки ``Content-Encoding: br`` и
  ``Vary: Accept-Encoding``;
* GZIP fallback всё ещё работает (если клиент послал ``gzip`` но не
  ``br`` — отвечаем тем же GZipMiddleware ниже в pipeline).

Зависимость ``brotli`` lazy-импортируется; при отсутствии extra
``compression`` middleware ничего не делает (no-op fallback на GZIP).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("middleware.brotli")

_JSON_TYPES = ("application/json", "+json")


class BrotliCompressionMiddleware:
    """ASGI middleware, сжимающий JSON-ответы алгоритмом Brotli.

    Args:
        app: внутренний ASGI app.
        minimum_size: минимальный размер ответа (байты) для активации.
        quality: уровень сжатия brotli (0-11).
    """

    def __init__(self, app: Any, *, minimum_size: int = 500, quality: int = 4) -> None:
        """Сохраняет downstream ASGI app + конфигурацию."""
        self.app = app
        self.minimum_size = minimum_size
        self.quality = quality
        self._brotli = self._try_import_brotli()

    @staticmethod
    def _try_import_brotli() -> Any | None:
        try:
            import brotli

            return brotli
        except ImportError:
            logger.info(
                "brotli не установлен — BrotliCompressionMiddleware no-op fallback "
                "(установите pip install brotli или extra=compression)"
            )
            return None

    @staticmethod
    def _wants_brotli(headers: list[tuple[bytes, bytes]]) -> bool:
        """Возвращает ``True``, если клиент шлёт ``Accept-Encoding: br``."""
        for name, value in headers:
            if name.lower() == b"accept-encoding":
                return b"br" in value.lower()
        return False

    @staticmethod
    def _is_json(headers: list[tuple[bytes, bytes]]) -> bool:
        for name, value in headers:
            if name.lower() == b"content-type":
                ct = value.decode("latin-1").lower()
                return any(token in ct for token in _JSON_TYPES)
        return False

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        """Обрабатывает ASGI events.

        Сжимаем только если:
        * scope[type] == "http";
        * клиент поддерживает brotli;
        * brotli-библиотека доступна;
        * Content-Type — JSON-семейство;
        * Body ≥ minimum_size.
        """
        if scope.get("type") != "http" or self._brotli is None:
            await self.app(scope, receive, send)
            return

        client_headers = scope.get("headers") or []
        if not self._wants_brotli(client_headers):
            await self.app(scope, receive, send)
            return

        buffer: list[bytes] = []
        response_started: list[bool] = [False]
        captured_status: list[int] = [200]
        captured_headers: list[list[tuple[bytes, bytes]]] = [[]]

        async def _send(message: dict[str, Any]) -> None:
            msg_type = message.get("type")
            if msg_type == "http.response.start":
                captured_status[0] = int(message.get("status", 200))
                captured_headers[0] = list(message.get("headers", []))
                response_started[0] = True
                return

            if msg_type == "http.response.body":
                buffer.append(bytes(message.get("body", b"")))
                if message.get("more_body"):
                    return
                # final chunk — решаем, сжимать или нет
                full_body = b"".join(buffer)
                if len(full_body) >= self.minimum_size and self._is_json(
                    captured_headers[0]
                ):
                    compressed = self._brotli.compress(full_body, quality=self.quality)
                    headers = [
                        (n, v)
                        for n, v in captured_headers[0]
                        if n.lower() not in (b"content-encoding", b"content-length")
                    ]
                    headers.append((b"content-encoding", b"br"))
                    headers.append(
                        (b"content-length", str(len(compressed)).encode("latin-1"))
                    )
                    # Добавим Vary
                    has_vary = any(n.lower() == b"vary" for n, _ in headers)
                    if not has_vary:
                        headers.append((b"vary", b"Accept-Encoding"))
                    await send(
                        {
                            "type": "http.response.start",
                            "status": captured_status[0],
                            "headers": headers,
                        }
                    )
                    await send(
                        {
                            "type": "http.response.body",
                            "body": compressed,
                            "more_body": False,
                        }
                    )
                    return

                # passthrough без сжатия
                await send(
                    {
                        "type": "http.response.start",
                        "status": captured_status[0],
                        "headers": captured_headers[0],
                    }
                )
                await send(
                    {
                        "type": "http.response.body",
                        "body": full_body,
                        "more_body": False,
                    }
                )
                return

            # любые другие message-типы пробрасываем как есть
            if response_started[0]:
                await send(message)

        await self.app(scope, receive, _send)


__all__ = ("BrotliCompressionMiddleware",)
