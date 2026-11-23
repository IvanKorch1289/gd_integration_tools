"""S193 W3: GZip compression middleware с path exclusion.

D-AUDIT-17601 fix (cycle 176): FastAPI's default GZipMiddleware
(BaseHTTPMiddleware pattern) incompatible с проектом's pure
ASGI middleware chain. На /docs, /redoc, /metrics → 500
'Internal server error' (start message suppressed, body dropped
or not re-sent).

Fix: pure ASGI GZipMiddleware с path exclusion. Paths /docs,
/docs/*, /redoc, /redoc/*, /metrics пропускаются через
compression (downstream handlers pass through unchanged).
"""

from __future__ import annotations

import asyncio
import gzip

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Paths that are KNOWN to break with compression (cycle 175 root
# cause: GZipMiddleware BaseHTTPMiddleware incompatibility with
# data_masking, response_cache, etc.). For these, compression is
# skipped — downstream handlers pass through unchanged.
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/metrics")


class GZipCompressionExcludingMiddleware:
    """Pure ASGI GZip middleware с path exclusion.

    Отличия от FastAPI's default:
    1. Path exclusion (список prefix'ов) — compression skipped для
       проблемных endpoints.
    2. Pure ASGI pattern (не BaseHTTPMiddleware) — pass start
       through, modify body on the fly.
    3. No double-buffering (compatible с project's ASGI chain).

    Notes:
        Потоковые ответы (SSE, бесконечный producer) **не сжимаются**:
        сжатие требует полного тела, а значит убивает инкрементальную
        доставку — клиент не получил бы ни одного события до конца потока.
        Такие ответы пробрасываются чанк за чанком без ``Content-Encoding``.

    """

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,
        compresslevel: int = 9,
        excluded_prefixes: tuple[str, ...] = EXCLUDED_PATH_PREFIXES,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.excluded_prefixes = excluded_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # D-AUDIT-17601 fix: skip compression для known-broken paths.
        path: str = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self.excluded_prefixes):
            # Pass through to downstream без compression.
            await self.app(scope, receive, send)
            return

        # Check Accept-Encoding: skip if client не поддерживает gzip.
        accept_encoding = ""
        for name, value in scope.get("headers", []):
            if name == b"accept-encoding":
                accept_encoding = value.decode("latin-1", errors="replace").lower()
                break
        if "gzip" not in accept_encoding:
            await self.app(scope, receive, send)
            return

        # Compress response.
        await self._compress(scope, receive, send)

    async def _compress(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Сжимает тело ответа, сохраняя потоковую (инкрементальную) доставку.

        Логика:

        1. ``http.response.start`` запоминается. Если в ответе уже есть
           ``Content-Encoding`` (тело закодировано ниже по цепочке) — ответ
           пробрасывается как есть: двойное сжатие запрещено.
        2. Первое сообщение тела с ``more_body=True`` означает **потоковый**
           ответ (SSE, бесконечный producer). Для такого ответа сжатие
           **отключается**: сжатие требует полного тела, поэтому клиент не
           получил бы ни одного события, пока поток не закончится (для
           бесконечного producer'а — никогда). ``start`` уходит как есть
           (без добавленных ``content-encoding``/``content-length``), чанки —
           по мере поступления.
        3. Обычный ответ копится целиком и сжимается, если размер ≥
           ``minimum_size``; иначе уходит несжатым.

        Решение «сжимать или нет» принимается **после возврата
        downstream-app** — только тогда известно всё тело. Раньше оно
        принималось по последнему message, и в ветке «body too small» клиенту
        уходил только последний message: накопленные промежуточные чанки
        терялись, и клиент получал (часто пустое) тело.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.
        """
        original_start: Message | None = None
        body_chunks: list[bytes] = []
        # True → ответ уже уходит клиенту «как есть» (потоковый или уже
        # закодированный ниже по цепочке): тело больше не трогаем.
        passthrough = False

        async def send_with_compression(message: Message) -> None:
            nonlocal original_start, passthrough
            if message["type"] == "http.response.start":
                # Buffer start, wait for body.
                original_start = message
                # PERF-6.6 P9: skip gzip если response уже compressed (brotli)
                # или имеет cache-control no-transform. Avoids double-compression
                # cost (gzip re-compressing brotli stream) + potential issues.
                #
                # P0 (аудит 2026-10-06): раньше здесь ставился только флаг
                # ``started = True``, а сам ``http.response.start`` НЕ
                # отправлялся. Тело при этом пробрасывалось как есть. Результат
                # — ответ без start-сообщения: нарушение ASGI-контракта
                # (сервер обязан слать start до body), из-за которого uvicorn
                # рвал соединение без ответа. Ветка достигалась, когда ниже по
                # цепочке ответ уже был закодирован (например, включён brotli).
                # Теперь original start уходит немедленно, а флаг означает
                # «сжатие не применяем».
                _has_encoding = any(
                    h[0].lower() == b"content-encoding"
                    for h in message.get("headers", [])
                )
                if _has_encoding:
                    await send(message)  # Pass start through untouched
                    passthrough = True  # Skip compression path entirely
            elif message["type"] == "http.response.body":
                if passthrough:
                    # Ответ уже уходит клиенту как есть — тело не трогаем.
                    await send(message)
                    return
                if message.get("more_body", False):
                    # Потоковый ответ: сжатие отключается (см. docstring).
                    # Накопленные ранее чанки (если приложение нарушило
                    # порядок сообщений) уходят перед текущим — порядок
                    # байт сохраняется.
                    passthrough = True
                    if original_start is not None:
                        await send(original_start)
                    for buffered in body_chunks:
                        await send(
                            {
                                "type": "http.response.body",
                                "body": buffered,
                                "more_body": True,
                            }
                        )
                    body_chunks.clear()
                    await send(message)
                    return
                # Обычный ответ — копим тело целиком.
                body_chunks.append(message.get("body", b""))
            else:
                # Other message types — pass through.
                await send(message)

        await self.app(scope, receive, send_with_compression)

        # Downstream завершился — всё тело известно, можно решать.
        if passthrough or original_start is None:
            # Ответ уже отправлен (потоковый / уже закодированный) либо
            # downstream не отправил start — отправлять нечего.
            return

        body_data = b"".join(body_chunks)
        if len(body_data) >= self.minimum_size:
            # PERF-6.6 P33: gzip.compress sync → run_in_executor.
            # Для bodies > 100KB sync gzip блокирует event loop
            # 1-5ms — с ExecutorThread pool это offloaded.
            # Малые bodies (< 1KB) остаются sync — overhead.
            if len(body_data) >= 1024:
                loop = asyncio.get_running_loop()
                compressed = await loop.run_in_executor(
                    None, gzip.compress, body_data, self.compresslevel
                )
            else:
                compressed = gzip.compress(body_data, compresslevel=self.compresslevel)
            # Update headers: Content-Encoding, Content-Length.
            from starlette.datastructures import MutableHeaders

            headers = MutableHeaders(raw=original_start.get("headers", []))
            headers["Content-Encoding"] = "gzip"
            headers["Content-Length"] = str(len(compressed))
            headers.add_vary_header("Accept-Encoding")
            new_start = dict(original_start)
            # ASGI requires (bytes, bytes) header pairs, but
            # MutableHeaders.items() yields (str, str). Sending
            # the str form makes uvicorn raise
            # "TypeError: cannot use a bytes pattern on a
            # string-like object" and drop the connection
            # without any response.
            #
            # Found on the live service: GET /openapi.json with
            # `Accept-Encoding: gzip` — i.e. what every browser
            # sends — returned an empty response (HTTP 000,
            # 0 bytes) for a 494 KB body, while the same request
            # without gzip returned 200. Any response body over
            # minimum_size was affected.
            new_start["headers"] = [
                (
                    k.encode("latin-1") if isinstance(k, str) else k,
                    v.encode("latin-1") if isinstance(v, str) else v,
                )
                for k, v in headers.items()
            ]
            await send(new_start)
            await send(
                {"type": "http.response.body", "body": compressed, "more_body": False}
            )
            return

        # Body too small — send uncompressed.
        # Раньше здесь уходил ТОЛЬКО последний message: накопленные
        # промежуточные чанки терялись, клиент получал (часто пустое) тело.
        # Отправляем накопленное тело целиком, сохраняя порядок чанков.
        await send(original_start)
        if not body_chunks:
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return
        last_index = len(body_chunks) - 1
        for index, chunk in enumerate(body_chunks):
            await send(
                {
                    "type": "http.response.body",
                    "body": chunk,
                    "more_body": index < last_index,
                }
            )
