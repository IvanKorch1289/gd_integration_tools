"""Регресс-тесты: ответ ASGI всегда доводится до конца.

Контекст дефекта
----------------
Три pure-ASGI middleware, переписывающих тело ответа, подавляли
``http.response.start`` и в отдельных ветках возвращались **без отправки
ответа**:

* ``ResponseCacheMiddleware`` — ветка «тело пустое» (``if not body: return``)
  и ветка ``304 Not Modified`` (отправлялся только ``http.response.start``);
* ``DataMaskingMiddleware`` — ветка «тело пустое»;
* ``PIIMaskingResponseMiddleware`` — ветки «тело пустое» и «маскировка
  упала» (неотмаскированное тело наружу не отдавалось, но и ответ не
  уходил).

Проверено на живом uvicorn: ветка «тело пустое» давала
``ERROR: ASGI callable returned without starting response`` и HTTP 500
вместо исходного ответа; ветка 304 — ``ERROR: ASGI callable returned
without completing response`` на каждом условном GET.

Контракт ASGI: после ``http.response.start`` обязан прийти
``http.response.body``; если ответ не начат — он обязан быть начат.
Нарушение этого контракта ломает keep-alive-соединение и превращает
любой успешный ответ в 500.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware
from src.backend.entrypoints.middlewares.pii_masking_response import (
    PIIMaskingResponseMiddleware,
)
from src.backend.entrypoints.middlewares.response_cache import (
    _USE_XXHASH,
    ResponseCacheMiddleware,
)

__all__ = (
    "TestResponseCacheCompletesResponse",
    "TestDataMaskingCompletesResponse",
    "TestPiiMaskingCompletesResponse",
)


def _scope(
    method: str = "GET",
    path: str = "/api",
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict[str, Any]:
    """Минимальный HTTP-scope для pure-ASGI middleware."""
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
    }


class _Receive:
    """Пустой receive-канал (body middleware'ами не читается)."""

    async def __call__(self) -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}


def _downstream(body: bytes, content_type: bytes = b"application/json"):
    """Downstream-приложение, отдающее заданное тело."""

    async def app(scope, receive, send):  # type: ignore[no-untyped-def]
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", content_type),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


class _Recorder:
    """Собирает ASGI-сообщения, отправленные middleware'ом."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def __call__(self, message: dict[str, Any]) -> None:
        self.messages.append(message)

    @property
    def types(self) -> list[str]:
        """Типы отправленных сообщений."""
        return [m["type"] for m in self.messages]

    @property
    def status(self) -> int | None:
        """HTTP-статус из ``http.response.start`` (None — ответа не было)."""
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message.get("status", 200))
        return None

    @property
    def body(self) -> bytes:
        """Склеенное тело ответа."""
        return b"".join(
            m.get("body", b"")
            for m in self.messages
            if m["type"] == "http.response.body"
        )


def _assert_response_complete(recorder: _Recorder) -> None:
    """Ответ начат И завершён — иначе uvicorn рвёт соединение."""
    assert "http.response.start" in recorder.types, recorder.types
    assert "http.response.body" in recorder.types, recorder.types
    assert recorder.types.index("http.response.start") < recorder.types.index(
        "http.response.body"
    ), recorder.types


@pytest.mark.unit
class TestResponseCacheCompletesResponse:
    """``ResponseCacheMiddleware`` не роняет ответ."""

    @pytest.mark.asyncio
    async def test_304_completes_response(self) -> None:
        """304 отправляет и body-сообщение (ответ закрывается)."""
        body = b'{"data":1}'
        if _USE_XXHASH:
            import xxhash

            etag = f'"{xxhash.xxh64(body).hexdigest()}"'
        else:
            from src.backend.entrypoints.middlewares._body_hash import etag_hash

            etag = etag_hash(body)

        middleware = ResponseCacheMiddleware(_downstream(body), max_age=120)
        recorder = _Recorder()

        await middleware(
            _scope(
                "GET",
                "/api",
                headers=[
                    (b"host", b"test"),
                    (b"if-none-match", etag.encode("latin-1")),
                ],
            ),
            _Receive(),
            recorder,
        )

        assert recorder.status == 304
        _assert_response_complete(recorder)

    @pytest.mark.asyncio
    async def test_empty_body_is_not_dropped(self) -> None:
        """Пустое тело не роняет ответ — original отправляется обратно."""
        middleware = ResponseCacheMiddleware(_downstream(b""), max_age=120)
        recorder = _Recorder()

        await middleware(_scope("GET", "/api"), _Receive(), recorder)

        assert recorder.status == 200
        _assert_response_complete(recorder)
        assert recorder.body == b""

    @pytest.mark.asyncio
    async def test_non_json_response_completes(self) -> None:
        """Non-JSON ответ (ветка skip-caching) тоже завершён."""
        middleware = ResponseCacheMiddleware(
            _downstream(b"plain", b"text/plain"), max_age=120
        )
        recorder = _Recorder()

        await middleware(_scope("GET", "/api"), _Receive(), recorder)

        _assert_response_complete(recorder)
        assert recorder.body == b"plain"


@pytest.mark.unit
class TestDataMaskingCompletesResponse:
    """``DataMaskingMiddleware`` не роняет ответ."""

    @pytest.mark.asyncio
    async def test_empty_body_is_not_dropped(self) -> None:
        """Пустое JSON-тело возвращается клиенту, а не теряется."""
        middleware = DataMaskingMiddleware(_downstream(b""))
        recorder = _Recorder()

        await middleware(_scope(), _Receive(), recorder)

        assert recorder.status == 200
        _assert_response_complete(recorder)
        assert recorder.body == b""


@pytest.mark.unit
class TestPiiMaskingCompletesResponse:
    """``PIIMaskingResponseMiddleware`` не роняет ответ и не течёт PII."""

    @pytest.mark.asyncio
    async def test_empty_body_is_not_dropped(self) -> None:
        """Пустое JSON-тело возвращается клиенту, а не теряется."""
        middleware = PIIMaskingResponseMiddleware(_downstream(b""))
        recorder = _Recorder()

        await middleware(_scope(), _Receive(), recorder)

        assert recorder.status == 200
        _assert_response_complete(recorder)
        assert recorder.body == b""

    @pytest.mark.asyncio
    async def test_masking_failure_fails_closed(self) -> None:
        """Сбой маскировки → fail-closed заглушка, исходное тело не утекает."""
        middleware = PIIMaskingResponseMiddleware(_downstream(b"not-json"))
        recorder = _Recorder()

        await middleware(_scope(), _Receive(), recorder)

        _assert_response_complete(recorder)
        parsed = json.loads(recorder.body.decode("utf-8"))
        assert parsed["error"] == "response_masking_failed"
        assert b"not-json" not in recorder.body
