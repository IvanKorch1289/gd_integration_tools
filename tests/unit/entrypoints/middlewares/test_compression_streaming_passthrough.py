"""Регресс: compression-middleware не теряет и не буферизует потоковые ответы.

Волна 2026-11-20: ``ResponseCacheMiddleware`` перестал буферизовать GET-ответы
целиком, и потоковые ответы (SSE/producer) действительно стали приходить
чанками. Раньше этот дефект был невидим — буферизация response_cache
прикрывала оба дефекта compression-middleware.

Дефект 1 (потеря данных)
------------------------
Ветка «body too small» отправляла клиенту **только последнее** сообщение
тела: накопленные промежуточные чанки терялись, и клиент получал вместо
ответа пустое (или обрезанное) тело.

Дефект 2 (streaming)
--------------------
Оба middleware копили тело целиком и отправляли его только после финального
чанка. Для потокового ответа клиент не получал ни одного события, пока поток
не закончится (для бесконечного producer'а — никогда). Сжатие требует
полного тела, поэтому для потоковых ответов оно отключается: ``start``
уходит как есть (без ``Content-Encoding``/``Content-Length``), чанки — по
мере поступления.

Инварианты, которые охраняют тесты ниже:

* потоковый ответ доходит до клиента целиком и **инкрементально**;
* обычный (одно сообщение тела) ответ сжимается ровно как раньше:
  ``≥ minimum_size`` → ``Content-Encoding: gzip``/``br``, иначе — как есть;
* многочанковый ответ меньше ``minimum_size`` теряет ни одного чанка.
"""

from __future__ import annotations

import asyncio
import gzip
import json

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.entrypoints.middlewares.brotli_compression import (
    BrotliCompressionMiddleware,
)
from src.backend.entrypoints.middlewares.gzip_compression_excluding import (
    GZipCompressionExcludingMiddleware,
)

GZIP_ACCEPT = [(b"accept-encoding", b"gzip, deflate, br")]
BR_ACCEPT = [(b"accept-encoding", b"br")]

#: Минимальный размер тела, с которого начинается сжатие.
MINIMUM_SIZE = 500

#: Чанки потокового ответа.
_CHUNKS: list[bytes] = [f"chunk-{index}\n".encode() for index in range(5)]

#: Тело заметно больше ``MINIMUM_SIZE``.
_BIG_BODY: bytes = json.dumps({"data": "x" * 1000}).encode()

#: Тело заметно меньше ``MINIMUM_SIZE``.
_SMALL_BODY: bytes = json.dumps({"data": "x"}).encode()


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    """Заглушка ``receive`` — тело запроса middleware'и не читают."""
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(
    app: ASGIApp,
    *,
    headers: list[tuple[bytes, bytes]] | None = None,
    path: str = "/stream",
) -> list[Message]:
    """Прогоняет HTTP-scope через ``app`` и собирает исходящие сообщения.

    Args:
        app: ASGI-приложение под тестом.
        headers: заголовки запроса (по умолчанию — клиент с gzip/br).
        path: путь запроса.

    Returns:
        Список отправленных ASGI-сообщений.

    """
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": list(GZIP_ACCEPT if headers is None else headers),
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, _receive, send)
    return sent


def _header_of(messages: list[Message], name: str) -> bytes | None:
    """Значение заголовка из первого ``http.response.start``.

    Args:
        messages: собранные ASGI-сообщения.
        name: имя заголовка.

    Returns:
        Значение заголовка либо ``None``, если его нет.

    """
    for msg in messages:
        if msg["type"] == "http.response.start":
            for key, value in msg.get("headers", []):
                if key.lower() == name.lower().encode("latin-1"):
                    return value
    return None


def _chunks_of(messages: list[Message]) -> list[bytes]:
    """Список чанков тела (каждое сообщение ``http.response.body``).

    Args:
        messages: собранные ASGI-сообщения.

    Returns:
        Список байтовых чанков в порядке отправки.

    """
    return [
        msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"
    ]


def _body_of(messages: list[Message]) -> bytes:
    """Склеенное тело из всех ``http.response.body``.

    Args:
        messages: собранные ASGI-сообщения.

    Returns:
        Склеенное тело ответа.

    """
    return b"".join(_chunks_of(messages))


def _streaming_app(
    chunks: list[bytes], *, headers: list[tuple[bytes, bytes]] | None = None
) -> ASGIApp:
    """ASGI-app, отдающая потоковый ответ.

    Все чанки, кроме последнего, идут с ``more_body=True`` — так ведёт себя
    ``StreamingResponse`` (SSE, генератор).

    Args:
        chunks: чанки тела.
        headers: заголовки ответа.

    Returns:
        ASGI-приложение.

    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": list(headers or [(b"content-type", b"text/event-stream")]),
            }
        )
        last = len(chunks) - 1
        for index, chunk in enumerate(chunks):
            await send(
                {"type": "http.response.body", "body": chunk, "more_body": index < last}
            )

    return app


def _single_app(
    body: bytes, *, headers: list[tuple[bytes, bytes]] | None = None
) -> ASGIApp:
    """ASGI-app, отдающая ответ одним сообщением тела (обычный ответ).

    Args:
        body: тело ответа.
        headers: заголовки ответа.

    Returns:
        ASGI-приложение.

    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": list(headers or [(b"content-type", b"application/json")]),
            }
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    return app


@pytest.mark.unit
class TestGzipStreaming:
    """GZip: потоковый ответ проходит насквозь, без сжатия."""

    async def test_streaming_chunks_reach_client_unchanged(self) -> None:
        """Все чанки потокового ответа доходят до клиента как есть."""
        middleware = GZipCompressionExcludingMiddleware(
            _streaming_app(_CHUNKS), minimum_size=MINIMUM_SIZE
        )

        messages = await _drive(middleware)

        assert messages[0]["type"] == "http.response.start", "start обязан быть первым"
        assert _header_of(messages, "content-encoding") is None, (
            "потоковый ответ не должен сжиматься"
        )
        assert _chunks_of(messages) == _CHUNKS, "чанки должны дойти в исходном виде"
        assert _body_of(messages) == b"".join(_CHUNKS)

    async def test_streaming_without_content_length_reaches_client(self) -> None:
        """Потоковый ответ без ``Content-Length`` доходит до клиента."""
        middleware = GZipCompressionExcludingMiddleware(
            _streaming_app(_CHUNKS, headers=[(b"content-type", b"text/event-stream")]),
            minimum_size=MINIMUM_SIZE,
        )

        messages = await _drive(middleware)

        assert _header_of(messages, "content-length") is None
        assert _body_of(messages) == b"".join(_CHUNKS)

    async def test_streaming_is_delivered_incrementally(self) -> None:
        """Первый чанк уходит клиенту ДО окончания producer'а.

        Ключевой инвариант дефекта 2: если middleware буферизует тело,
        producer не сможет продолжить работу (он ждёт первого чанка) и
        тест упадёт по таймауту.
        """
        release = asyncio.Event()
        received: list[Message] = []

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send(
                {"type": "http.response.body", "body": b"first\n", "more_body": True}
            )
            await release.wait()
            await send(
                {"type": "http.response.body", "body": b"second\n", "more_body": False}
            )

        async def send(message: Message) -> None:
            received.append(message)
            if (
                message["type"] == "http.response.body"
                and message.get("body") == b"first\n"
            ):
                release.set()

        middleware = GZipCompressionExcludingMiddleware(app, minimum_size=MINIMUM_SIZE)
        scope: Scope = {
            "type": "http",
            "method": "GET",
            "path": "/stream",
            "headers": list(GZIP_ACCEPT),
        }

        await asyncio.wait_for(middleware(scope, _receive, send), timeout=5)

        assert _body_of(received) == b"first\nsecond\n"


@pytest.mark.unit
class TestGzipSingleMessage:
    """GZip: обычный ответ сжимается ровно как раньше."""

    async def test_big_body_is_compressed(self) -> None:
        """Ответ ≥ ``minimum_size`` сжимается и распаковывается без потерь."""
        middleware = GZipCompressionExcludingMiddleware(
            _single_app(_BIG_BODY), minimum_size=MINIMUM_SIZE
        )

        messages = await _drive(middleware)

        assert _header_of(messages, "content-encoding") == b"gzip"
        raw = _body_of(messages)
        assert gzip.decompress(raw) == _BIG_BODY

    async def test_small_body_is_not_compressed(self) -> None:
        """Ответ < ``minimum_size`` уходит несжатым и без потерь."""
        middleware = GZipCompressionExcludingMiddleware(
            _single_app(_SMALL_BODY), minimum_size=MINIMUM_SIZE
        )

        messages = await _drive(middleware)

        assert _header_of(messages, "content-encoding") is None
        assert _body_of(messages) == _SMALL_BODY

    async def test_multi_chunk_small_body_keeps_every_chunk(self) -> None:
        """Многочанковый ответ < ``minimum_size`` теряет ни одного чанка.

        Регрессия дефекта 1: в ветке «body too small» клиенту уходил только
        последний message, накопленное тело пропадало.
        """
        chunks = [b"chunk-0\n", b"chunk-1\n", b"chunk-2\n"]

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/plain")],
                }
            )
            for chunk in chunks:
                await send({"type": "http.response.body", "body": chunk})

        middleware = GZipCompressionExcludingMiddleware(app, minimum_size=MINIMUM_SIZE)

        messages = await _drive(middleware)

        assert _header_of(messages, "content-encoding") is None
        assert _body_of(messages) == b"".join(chunks), "все чанки обязаны на месте"


@pytest.mark.unit
class TestBrotliCompression:
    """Brotli: JSON сжимается, потоковый ответ — нет."""

    async def test_big_json_body_is_compressed(self) -> None:
        """JSON ≥ ``minimum_size`` сжимается алгоритмом brotli."""
        middleware = BrotliCompressionMiddleware(
            _single_app(_BIG_BODY), minimum_size=MINIMUM_SIZE
        )
        if middleware._brotli is None:  # pragma: no cover - опциональный extra
            pytest.skip("brotli не установлен")

        messages = await _drive(middleware, headers=BR_ACCEPT)

        assert _header_of(messages, "content-encoding") == b"br"
        raw = _body_of(messages)
        assert middleware._brotli.decompress(raw) == _BIG_BODY

    async def test_small_json_body_is_not_compressed(self) -> None:
        """JSON < ``minimum_size`` уходит несжатым."""
        middleware = BrotliCompressionMiddleware(
            _single_app(_SMALL_BODY), minimum_size=MINIMUM_SIZE
        )
        if middleware._brotli is None:  # pragma: no cover - опциональный extra
            pytest.skip("brotli не установлен")

        messages = await _drive(middleware, headers=BR_ACCEPT)

        assert _header_of(messages, "content-encoding") is None
        assert _body_of(messages) == _SMALL_BODY

    async def test_streaming_response_is_not_compressed(self) -> None:
        """Потоковый ответ не сжимается, все чанки доходят до клиента."""
        middleware = BrotliCompressionMiddleware(
            _streaming_app(_CHUNKS, headers=[(b"content-type", b"application/json")]),
            minimum_size=MINIMUM_SIZE,
        )
        if middleware._brotli is None:  # pragma: no cover - опциональный extra
            pytest.skip("brotli не установлен")

        messages = await _drive(middleware, headers=BR_ACCEPT)

        assert _header_of(messages, "content-encoding") is None
        assert _chunks_of(messages) == _CHUNKS
        assert _body_of(messages) == b"".join(_CHUNKS)

    async def test_multi_chunk_small_body_keeps_every_chunk(self) -> None:
        """Многочанковый ответ < ``minimum_size`` теряет ни одного чанка."""
        chunks = [b"chunk-0\n", b"chunk-1\n", b"chunk-2\n"]

        async def app(scope: Scope, receive: Receive, send: Send) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            for chunk in chunks:
                await send({"type": "http.response.body", "body": chunk})

        middleware = BrotliCompressionMiddleware(app, minimum_size=MINIMUM_SIZE)
        if middleware._brotli is None:  # pragma: no cover - опциональный extra
            pytest.skip("brotli не установлен")

        messages = await _drive(middleware, headers=BR_ACCEPT)

        assert _header_of(messages, "content-encoding") is None
        assert _body_of(messages) == b"".join(chunks)


@pytest.mark.unit
async def test_gzip_and_brotli_keep_streaming_chunks_in_order() -> None:
    """Оба middleware вместе не теряют и не переставляют чанки потока."""
    app = _streaming_app(_CHUNKS)

    for middleware in (
        GZipCompressionExcludingMiddleware(app, minimum_size=MINIMUM_SIZE),
        BrotliCompressionMiddleware(app, minimum_size=MINIMUM_SIZE),
    ):
        messages = await _drive(middleware)
        assert _chunks_of(messages) == _CHUNKS
        assert _header_of(messages, "content-encoding") is None
