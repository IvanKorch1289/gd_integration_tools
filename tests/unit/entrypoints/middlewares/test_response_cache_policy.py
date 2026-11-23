"""Политика кэширования и streaming в ``ResponseCacheMiddleware``.

Волна 2026-11-20 (аудит prod-readiness, находки 3.1 и 3.2)
-----------------------------------------------------------

3.1 — Политика. Раньше middleware жёстко возвращал ``public, max-age=N``
для любого 200 JSON GET и удалял исходные ``ETag``/``Cache-Control``
downstream. Итог: политика endpoint'а (``no-store``) терялась, а
персонализированные ответы объявлялись публично кэшируемыми — общий
кэш (CDN/proxy) мог отдать чужой ответ.

3.2 — Streaming. Тело накапливалось для ВСЕХ ответов, а проверка
content-type выполнялась ПОСЛЕ накопления: SSE отдавался только после
завершения downstream, бесконечный поток вешал ответ, большие ответы
буферизовались в памяти.

Контракт после фикса
--------------------
* ``public`` — только явный opt-in endpoint'а (``Cache-Control: public``)
  И анонимный запрос; персонализированный запрос → ``private``;
* ``Set-Cookie`` в ответе → ``no-store`` (перекрывает opt-in);
* политика endpoint'а сохраняется; ``max-age`` добавляется, если нет
  ``max-age`` / ``s-maxage`` / ``no-store``;
* без политики endpoint'а → ``private, max-age=N`` (никогда не public);
* политика 304 идентична политике 200 (единый код расчёта);
* не-кэшируемые ответы (не-JSON, ``Content-Encoding``, поток, тело
  больше лимита) идут в passthrough: без буферизации и без изменения
  заголовков; ETag для них не считается.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.response_cache import ResponseCacheMiddleware

#: Тело JSON-ответа по умолчанию.
_BODY = b'{"data":1}'


class _ClientDisconnect(Exception):
    """Имитация разрыва соединения клиентом (ошибка в ``send``)."""


def _scope(
    headers: list[tuple[bytes, bytes]] | None = None,
    state: dict[str, Any] | None = None,
    method: str = "GET",
) -> dict[str, Any]:
    """HTTP-scope для pure-ASGI middleware.

    Args:
        headers: Заголовки запроса.
        state: Значение ``scope['state']`` (например, ``{'auth': ...}``).
        method: HTTP-метод.

    Returns:
        Готовый scope.

    """
    scope: dict[str, Any] = {
        "type": "http",
        "method": method,
        "url": "http://test/api",
        "path": "/api",
        "headers": list(headers or []),
        "query_string": b"",
    }
    if state is not None:
        scope["state"] = state
    return scope


async def _receive() -> dict[str, Any]:
    """Пустой receive-канал (тело запроса middleware'ем не читается)."""
    return {"type": "http.request", "body": b"", "more_body": False}


class _Recorder:
    """Собирает ASGI-сообщения, отправленные middleware'ем."""

    def __init__(self) -> None:
        """Инициализирует рекордер (события — для проверок порядка)."""
        self.messages: list[dict[str, Any]] = []
        self.start_received = asyncio.Event()
        self.body_received = asyncio.Event()

    async def __call__(self, message: dict[str, Any]) -> None:
        """Записывает отправленное ASGI-сообщение."""
        self.messages.append(message)
        if message["type"] == "http.response.start":
            self.start_received.set()
        elif message["type"] == "http.response.body":
            self.body_received.set()

    @property
    def headers(self) -> dict[bytes, bytes]:
        """Заголовки ``http.response.start`` (ключи — в нижнем регистре)."""
        for message in self.messages:
            if message["type"] == "http.response.start":
                return {key.lower(): value for key, value in message["headers"]}
        return {}

    @property
    def status(self) -> int | None:
        """HTTP-статус ответа (None — ответа не было)."""
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message.get("status", 200))
        return None

    @property
    def body(self) -> bytes:
        """Склеенное тело ответа."""
        return b"".join(
            message.get("body", b"")
            for message in self.messages
            if message["type"] == "http.response.body"
        )

    @property
    def body_messages(self) -> list[dict[str, Any]]:
        """Body-сообщения ответа (по порядку отправки)."""
        return [
            message
            for message in self.messages
            if message["type"] == "http.response.body"
        ]

    @property
    def policy(self) -> str:
        """Значение ``Cache-Control`` из ответа (пустая строка — нет)."""
        return self.headers.get(b"cache-control", b"").decode("latin-1")


def _json_app(
    body: bytes = _BODY,
    *,
    status: int = 200,
    extra_headers: tuple[tuple[bytes, bytes], ...] = (),
    content_length: bool = True,
) -> Any:
    """Downstream-приложение, отдающее JSON-ответ.

    Args:
        body: Тело ответа.
        status: HTTP-статус.
        extra_headers: Дополнительные заголовки ответа.
        content_length: Добавлять ли заголовок ``Content-Length``.

    Returns:
        ASGI-приложение.

    """

    async def app(scope: Any, receive: Any, send: Any) -> None:
        headers: list[tuple[bytes, bytes]] = [(b"content-type", b"application/json")]
        if content_length:
            headers.append((b"content-length", str(len(body)).encode("latin-1")))
        headers.extend(extra_headers)
        await send(
            {"type": "http.response.start", "status": status, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body})

    return app


@pytest.mark.unit
class TestCacheControlPolicy:
    """Политика ``Cache-Control`` (дефект 3.1)."""

    @pytest.mark.asyncio
    async def test_authorization_request_is_not_public(self) -> None:
        """Authorization-запрос → в Cache-Control нет ``public``."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(
            _scope(headers=[(b"authorization", b"Bearer secret")]), _receive, recorder
        )

        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_api_key_request_is_not_public(self) -> None:
        """X-API-Key → в Cache-Control нет ``public``."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(
            _scope(headers=[(b"x-api-key", b"secret-key")]), _receive, recorder
        )

        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_cookie_request_is_not_public(self) -> None:
        """Cookie → в Cache-Control нет ``public``."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(
            _scope(headers=[(b"cookie", b"session=abc")]), _receive, recorder
        )

        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_state_auth_request_is_not_public(self) -> None:
        """``scope['state']['auth']`` → в Cache-Control нет ``public``."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(_scope(state={"auth": object()}), _receive, recorder)

        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_set_cookie_response_is_no_store(self) -> None:
        """Ответ с ``Set-Cookie`` → ``no-store`` (перекрывает opt-in public)."""
        middleware = ResponseCacheMiddleware(
            _json_app(
                extra_headers=(
                    (b"cache-control", b"public"),
                    (b"set-cookie", b"session=abc"),
                )
            ),
            max_age=120,
        )
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert recorder.policy == "no-store"

    @pytest.mark.asyncio
    async def test_endpoint_no_store_is_preserved(self) -> None:
        """Политика endpoint'а ``no-store`` сохраняется (не перебита)."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"no-store"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert recorder.policy == "no-store"

    @pytest.mark.asyncio
    async def test_endpoint_public_opt_in_for_anonymous_request(self) -> None:
        """Явный opt-in endpoint'а + анонимный запрос → ``public`` остаётся."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert "public" in recorder.policy
        # TTL добавляется: в политике endpoint'а не было max-age/s-maxage.
        assert "max-age=120" in recorder.policy

    @pytest.mark.asyncio
    async def test_endpoint_public_downgraded_for_authenticated_request(self) -> None:
        """Opt-in endpoint'а + аутентифицированный запрос → ``public`` отсутствует."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"cache-control", b"public"),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(
            _scope(headers=[(b"authorization", b"Bearer secret")]), _receive, recorder
        )

        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_anonymous_request_without_endpoint_policy_is_private(self) -> None:
        """Анонимный запрос без политики endpoint'а → ``private`` (не public)."""
        middleware = ResponseCacheMiddleware(_json_app(), max_age=120)
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert "public" not in recorder.policy
        assert recorder.policy == "private, max-age=120"


@pytest.mark.unit
class TestConditionalGetPolicy:
    """Условный GET: политика 304 идентична политике 200."""

    @pytest.mark.asyncio
    async def test_304_policy_matches_200(self) -> None:
        """304 → та же директива Cache-Control, есть ETag, тела нет."""
        middleware = ResponseCacheMiddleware(_json_app(), max_age=120)

        first = _Recorder()
        await middleware(_scope(), _receive, first)
        etag = first.headers[b"etag"].decode("latin-1")
        assert etag

        second = _Recorder()
        await middleware(
            _scope(headers=[(b"if-none-match", etag.encode("latin-1"))]),
            _receive,
            second,
        )

        assert second.status == 304
        assert second.headers[b"etag"].decode("latin-1") == etag
        assert second.policy == first.policy
        assert second.body == b""
        # ASGI-контракт: ответ начат И завершён.
        assert second.body_messages[-1]["more_body"] is False

    @pytest.mark.asyncio
    async def test_304_preserves_representation_headers(self) -> None:
        """304 сохраняет заголовки представления (RFC 7232 §4.1).

        ``Vary``/``Expires``/``Content-Location`` описывают представление и
        обязаны совпадать с ответом 200; ``Content-Length`` не переносится —
        у 304 нет тела.

        Args:
            None.
        """
        middleware = ResponseCacheMiddleware(
            _json_app(
                extra_headers=(
                    (b"vary", b"Accept-Encoding"),
                    (b"expires", b"Wed, 21 Oct 2026 07:28:00 GMT"),
                    (b"content-location", b"/api/resource"),
                )
            ),
            max_age=120,
        )

        first = _Recorder()
        await middleware(_scope(), _receive, first)
        etag = first.headers[b"etag"].decode("latin-1")

        second = _Recorder()
        await middleware(
            _scope(headers=[(b"if-none-match", etag.encode("latin-1"))]),
            _receive,
            second,
        )

        assert second.status == 304
        assert second.headers[b"vary"] == b"Accept-Encoding"
        assert second.headers[b"expires"] == b"Wed, 21 Oct 2026 07:28:00 GMT"
        assert second.headers[b"content-location"] == b"/api/resource"
        assert b"content-length" not in second.headers


@pytest.mark.unit
class TestStreamingPassthrough:
    """Streaming / обход буферизации (дефект 3.2)."""

    @pytest.mark.asyncio
    async def test_sse_first_chunk_sent_before_producer_finishes(self) -> None:
        """SSE: первый чанк уходит клиенту ДО завершения producer'а."""
        release = asyncio.Event()

        async def sse_app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"data: 1\n\n",
                    "more_body": True,
                }
            )
            # Producer ждёт разрешения — ответ ещё не завершён.
            await release.wait()
            await send(
                {
                    "type": "http.response.body",
                    "body": b"data: 2\n\n",
                    "more_body": False,
                }
            )

        middleware = ResponseCacheMiddleware(sse_app, max_age=120)
        recorder = _Recorder()
        task = asyncio.create_task(middleware(_scope(), _receive, recorder))
        try:
            await asyncio.wait_for(recorder.body_received.wait(), timeout=2)
            assert b"data: 1\n\n" in recorder.body
            assert not task.done(), "producer ещё работает — ответ не завершён"
        finally:
            release.set()
            await asyncio.wait_for(task, timeout=2)

        assert b"data: 2\n\n" in recorder.body

    @pytest.mark.asyncio
    async def test_infinite_producer_does_not_block_response(self) -> None:
        """Бесконечный producer → клиент получает первый чанк (ответ не «висит»)."""

        async def infinite_app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"text/event-stream")],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b"data: first\n\n",
                    "more_body": True,
                }
            )
            while True:
                await asyncio.sleep(3600)

        middleware = ResponseCacheMiddleware(infinite_app, max_age=120)
        recorder = _Recorder()
        task = asyncio.create_task(middleware(_scope(), _receive, recorder))
        try:
            await asyncio.wait_for(recorder.body_received.wait(), timeout=2)
            assert b"data: first\n\n" in recorder.body
        finally:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    @pytest.mark.asyncio
    async def test_response_over_size_limit_is_not_cached(self) -> None:
        """Ответ больше лимита → ETag не считается, отправка идёт до конца тела."""
        payload = b"x" * 4096
        body_allowed = asyncio.Event()

        async def big_app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(payload)).encode("latin-1")),
                    ],
                }
            )
            # Тело ещё не отправлено — клиент уже должен получить start.
            await body_allowed.wait()
            await send({"type": "http.response.body", "body": payload})

        middleware = ResponseCacheMiddleware(big_app, max_age=120, max_body_size=1024)
        recorder = _Recorder()
        task = asyncio.create_task(middleware(_scope(), _receive, recorder))
        try:
            await asyncio.wait_for(recorder.start_received.wait(), timeout=2)
            assert b"etag" not in recorder.headers
            assert recorder.body == b""
        finally:
            body_allowed.set()
            await asyncio.wait_for(task, timeout=2)

        assert recorder.body == payload

    @pytest.mark.asyncio
    async def test_body_over_size_limit_flushed_without_etag(self) -> None:
        """Тело больше лимита (без Content-Length) → сброс + passthrough, без ETag."""
        payload = b"y" * 4096

        async def big_app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send({"type": "http.response.body", "body": payload})

        middleware = ResponseCacheMiddleware(big_app, max_age=120, max_body_size=1024)
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        # ETag строится по всему телу — при превышении лимита он не считается.
        assert b"etag" not in recorder.headers
        assert recorder.status == 200
        assert recorder.body == payload
        # Passthrough пересылает тело «как есть»: отсутствие ``more_body``
        # по ASGI-контракту равносильно ``more_body=False``.
        assert recorder.body_messages[-1].get("more_body", False) is False

    @pytest.mark.asyncio
    async def test_empty_body_returns_200_without_etag(self) -> None:
        """Пустое тело → 200 без ETag, ответ корректно завершён."""
        middleware = ResponseCacheMiddleware(_json_app(b""), max_age=120)
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert recorder.status == 200
        assert b"etag" not in recorder.headers
        assert recorder.body == b""
        assert recorder.body_messages[-1]["more_body"] is False

    @pytest.mark.asyncio
    async def test_chunked_json_is_passed_through_in_order(self) -> None:
        """Chunked JSON (``more_body=True``) → passthrough, порядок сохранён."""

        async def chunked_app(scope: Any, receive: Any, send: Any) -> None:
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [(b"content-type", b"application/json")],
                }
            )
            await send(
                {"type": "http.response.body", "body": b'{"a":', "more_body": True}
            )
            await send(
                {"type": "http.response.body", "body": b"1}", "more_body": False}
            )

        middleware = ResponseCacheMiddleware(chunked_app, max_age=120)
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert b"etag" not in recorder.headers
        assert [m["body"] for m in recorder.body_messages] == [b'{"a":', b"1}"]
        assert recorder.body == b'{"a":1}'

    @pytest.mark.asyncio
    @pytest.mark.parametrize("encoding", [b"gzip", b"br"])
    async def test_compressed_response_is_passed_through(self, encoding: bytes) -> None:
        """Ответ с ``Content-Encoding`` → passthrough, ETag нет."""
        middleware = ResponseCacheMiddleware(
            _json_app(extra_headers=((b"content-encoding", encoding),)), max_age=120
        )
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert b"etag" not in recorder.headers
        # Заголовки ответа не меняются (passthrough без модификаций).
        assert b"cache-control" not in recorder.headers
        assert recorder.body == _BODY

    @pytest.mark.asyncio
    async def test_final_body_message_completes_response(self) -> None:
        """Финальное ``http.response.body`` с ``more_body=False`` присутствует."""
        middleware = ResponseCacheMiddleware(_json_app(), max_age=120)
        recorder = _Recorder()

        await middleware(_scope(), _receive, recorder)

        assert recorder.body_messages[-1]["more_body"] is False
        assert recorder.body_messages[-1]["body"] == _BODY


@pytest.mark.unit
class TestErrorPropagation:
    """Ошибки не подавляются."""

    @pytest.mark.asyncio
    async def test_client_disconnect_exception_propagates(self) -> None:
        """Разрыв соединения (исключение из ``send``) пробрасывается наружу."""

        async def failing_send(message: dict[str, Any]) -> None:
            raise _ClientDisconnect("connection closed")

        middleware = ResponseCacheMiddleware(_json_app(), max_age=120)

        with pytest.raises(_ClientDisconnect):
            await middleware(_scope(), _receive, failing_send)
