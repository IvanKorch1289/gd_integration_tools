"""Residual HTTP-cache risks (audit 2026-11-23, stage 3).

Three points fixed in ``src/backend/entrypoints/middlewares/response_cache.py``:

1. **3.1 — tenant-dependent response must not be published in a shared cache.**
   An anonymous request with ``X-Tenant-ID`` is served with THAT tenant's data
   (``TenantMiddleware`` takes the header when there is no principal), but the
   personalization check saw only ``authorization``/``x-api-key``/``cookie`` →
   an endpoint with an explicit ``public`` opt-in published a tenant-dependent
   response as ``public``. Now ``x-tenant-id`` also makes the request
   personalized → ``private`` (and ``s-maxage`` is dropped). ``Vary`` is not
   used as a substitute for authorization.

2. **3.2 — ``If-None-Match`` forms (RFC 9110 §13.1.2).** ``*``, a
   comma-separated list and weak tags (``W/"..."``) must be honoured; the
   comparison for ``If-None-Match`` is the WEAK one (RFC 9111 §4.2.2).

3. **3.3 — strong ETag vs gzip/identity representations.** The response body
   may be compressed by an OUTER middleware (``gzip`` order=900,
   ``brotli`` order=920 — outer to ``response_cache`` order=710), so the
   transmitted bytes differ from the identity bytes the ETag is computed
   over. A strong validator must identify the transmitted representation
   (RFC 9111 §4.1) → when the client accepts a content-coding, the ETag is
   weak (``W/"..."``). ``Vary: Accept-Encoding`` is set by the compression
   middlewares, so a shared cache still distinguishes the variants.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.entrypoints.middlewares.response_cache import ResponseCacheMiddleware

_BODY = b'{"ok":true}'


class _Recorder:
    """Собирает сообщения ответа."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    @property
    def headers(self) -> dict[bytes, bytes]:
        """Заголовки ``http.response.start`` (ключи — в нижнем регистре)."""
        for message in self.messages:
            if message["type"] == "http.response.start":
                return {key.lower(): value for key, value in message["headers"]}
        return {}

    @property
    def status(self) -> int:
        """HTTP-статус ответа."""
        for message in self.messages:
            if message["type"] == "http.response.start":
                return int(message.get("status", 200))
        return 0

    @property
    def policy(self) -> str:
        """Значение ``Cache-Control`` из ответа."""
        return self.headers.get(b"cache-control", b"").decode("latin-1")

    @property
    def etag(self) -> str:
        """Значение ``ETag`` из ответа."""
        return self.headers.get(b"etag", b"").decode("latin-1")


def _json_app(extra_headers: tuple[tuple[bytes, bytes], ...] = ()) -> Any:
    """Downstream-приложение, отдающее JSON-ответ.

    Args:
        extra_headers: Дополнительные заголовки ответа.

    Returns:
        ASGI-приложение.

    """

    async def app(scope: Any, receive: Any, send: Any) -> None:
        headers: list[tuple[bytes, bytes]] = [
            (b"content-type", b"application/json"),
            (b"content-length", str(len(_BODY)).encode("latin-1")),
        ]
        headers.extend(extra_headers)
        await send({"type": "http.response.start", "status": 200, "headers": headers})
        await send({"type": "http.response.body", "body": _BODY})

    return app


async def _run(
    request_headers: list[tuple[bytes, bytes]],
    response_headers: tuple[tuple[bytes, bytes], ...] = (),
) -> _Recorder:
    """Прогнать запрос через middleware и вернуть записанный ответ.

    Args:
        request_headers: Заголовки запроса.
        response_headers: Дополнительные заголовки ответа endpoint'а.

    Returns:
        Записанные сообщения ответа.

    """
    recorder = _Recorder()

    async def send(message: dict[str, Any]) -> None:
        recorder.messages.append(message)

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    middleware = ResponseCacheMiddleware(_json_app(response_headers), max_age=120)
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/api",
        "headers": request_headers,
        "state": {},
    }
    await middleware(scope, receive, send)
    return recorder


@pytest.mark.unit
class TestTenantHeaderIsPersonalized:
    """3.1 — tenant-зависимый ответ не публикуется в общем кэше."""

    @pytest.mark.asyncio
    async def test_tenant_header_request_is_not_public(self) -> None:
        """``X-Tenant-ID`` + opt-in ``public`` → ``private``, не ``public``."""
        recorder = await _run(
            [(b"x-tenant-id", b"tenant-b")],
            ((b"cache-control", b"public, max-age=60"),),
        )
        assert "public" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_s_maxage_dropped_for_tenant_request(self) -> None:
        """``s-maxage`` выбрасывается для tenant-зависимого запроса."""
        recorder = await _run(
            [(b"x-tenant-id", b"tenant-b")],
            ((b"cache-control", b"public, s-maxage=300"),),
        )
        assert "s-maxage" not in recorder.policy
        assert "private" in recorder.policy

    @pytest.mark.asyncio
    async def test_public_opt_in_survives_for_anonymous_request(self) -> None:
        """Без tenant-заголовка opt-in ``public`` сохраняется."""
        recorder = await _run([], ((b"cache-control", b"public, max-age=60"),))
        assert "public" in recorder.policy

    @pytest.mark.asyncio
    async def test_endpoint_no_store_preserved(self) -> None:
        """Политика endpoint'а (``no-store``) не перетирается."""
        recorder = await _run(
            [(b"x-tenant-id", b"tenant-b")], ((b"cache-control", b"no-store"),)
        )
        assert "no-store" in recorder.policy


@pytest.mark.unit
class TestIfNoneMatchForms:
    """3.2 — формы ``If-None-Match`` (RFC 9110 §13.1.2)."""

    @pytest.mark.asyncio
    async def test_star_matches(self) -> None:
        """``If-None-Match: *`` → 304 (ресурс существует)."""
        recorder = await _run([(b"if-none-match", b"*")])
        assert recorder.status == 304

    @pytest.mark.asyncio
    async def test_list_matches(self) -> None:
        """Список тегов: совпадение любого элемента → 304."""
        recorder = await _run([], ((b"cache-control", b"private"),))
        etag = recorder.etag
        recorder = await _run(
            [(b"if-none-match", f'"other", {etag}'.encode("latin-1"))]
        )
        assert recorder.status == 304

    @pytest.mark.asyncio
    async def test_weak_tag_matches_strong_response(self) -> None:
        """Слабый ``W/"..."`` совпадает с сильным ETag (слабое сравнение)."""
        recorder = await _run([])
        etag = recorder.etag
        recorder = await _run([(b"if-none-match", f"W/{etag}".encode("latin-1"))])
        assert recorder.status == 304

    @pytest.mark.asyncio
    async def test_non_matching_returns_200(self) -> None:
        """Несовпадающий тег → 200 с телом."""
        recorder = await _run([(b"if-none-match", b'"nope"')])
        assert recorder.status == 200

    @pytest.mark.asyncio
    async def test_client_strong_tag_matches_weak_response_etag(self) -> None:
        """Клиент присылает сильный тег, ответ — слабый: совпадение есть."""
        recorder = await _run([(b"accept-encoding", b"gzip")])
        weak = recorder.etag
        assert weak.startswith("W/"), f"ожидался слабый ETag, получен {weak!r}"
        recorder = await _run(
            [
                (b"accept-encoding", b"gzip"),
                (b"if-none-match", weak[2:].encode("latin-1")),
            ]
        )
        assert recorder.status == 304


@pytest.mark.unit
class TestWeakEtagWhenCompressionPossible:
    """3.3 — ETag против gzip/identity-представлений."""

    @pytest.mark.asyncio
    async def test_gzip_accept_encoding_yields_weak_etag(self) -> None:
        """Клиент принимает gzip → ETag слабый (тело может быть сжато)."""
        recorder = await _run([(b"accept-encoding", b"gzip, deflate")])
        assert recorder.etag.startswith("W/")

    @pytest.mark.asyncio
    async def test_brotli_accept_encoding_yields_weak_etag(self) -> None:
        """Клиент принимает br → ETag слабый."""
        recorder = await _run([(b"accept-encoding", b"br")])
        assert recorder.etag.startswith("W/")

    @pytest.mark.asyncio
    async def test_without_accept_encoding_etag_is_strong(self) -> None:
        """Без ``Accept-Encoding`` ETag сильный (тело не сжимается)."""
        recorder = await _run([])
        assert not recorder.etag.startswith("W/")
        assert recorder.etag.startswith('"')

    @pytest.mark.asyncio
    async def test_weak_etag_response_carries_vary(self) -> None:
        """Слабый ETag → ответ несёт ``Vary: Accept-Encoding``.

        Представление зависит от content-coding, значит shared cache обязан
        различать варианты по кодировке (RFC 9111 §4.1). Middleware'и сжатия
        добавляют ``Vary`` только когда реально сжали тело — у 304 тела нет,
        поэтому заголовок добавляет сам response_cache.
        """
        recorder = await _run([(b"accept-encoding", b"gzip")])
        assert recorder.etag.startswith("W/")
        assert "accept-encoding" in recorder.headers[b"vary"].decode("latin-1").lower()

    @pytest.mark.asyncio
    async def test_304_carries_vary_with_weak_etag(self) -> None:
        """304 со слабым ETag тоже несёт ``Vary: Accept-Encoding``."""
        recorder = await _run([(b"accept-encoding", b"gzip")])
        weak = recorder.etag
        recorder = await _run(
            [(b"accept-encoding", b"gzip"), (b"if-none-match", weak.encode("latin-1"))]
        )
        assert recorder.status == 304
        assert "accept-encoding" in recorder.headers[b"vary"].decode("latin-1").lower()

    @pytest.mark.asyncio
    async def test_strong_etag_response_has_no_vary(self) -> None:
        """Без content-coding ETag сильный — ``Vary`` не нужен."""
        recorder = await _run([])
        assert not recorder.etag.startswith("W/")
        assert b"vary" not in recorder.headers

    @pytest.mark.asyncio
    async def test_304_keeps_same_etag_form(self) -> None:
        """304 возвращает тот же ETag (в т.ч. слабую форму)."""
        recorder = await _run([(b"accept-encoding", b"gzip")])
        weak = recorder.etag
        recorder = await _run(
            [(b"accept-encoding", b"gzip"), (b"if-none-match", weak.encode("latin-1"))]
        )
        assert recorder.status == 304
        assert recorder.etag == weak
