"""Регрессия P0 (аудит 2026-10-06): сжатие ломало маскирование PII.

Наблюдаемое на живом сервере поведение
--------------------------------------
``GET /api/v1/admin/actions`` с ``Accept-Encoding: gzip`` — то есть ровно то,
что шлёт каждый браузер — возвращал::

    HTTP/1.1 200 OK
    content-encoding: gzip
    content-length: 104
    {"error":"response_masking_failed",
     "detail":"PII masking failed; original response withheld for safety"}

Тело было **несжатым** plain-JSON под меткой ``gzip``. httpx падал с
``DecodingError: Error -3 while decompressing data: incorrect header check``;
curl отдавал мусор молча, поэтому cURL-батарея дефект не ловила.
Настоящий ответ (2562 байта списка actions) терялся целиком, а клиент
получал заглушку с кодом 200.

Причинная цепочка (подтверждена логом сервера)
-----------------------------------------------
``UnicodeDecodeError: 'utf-8' codec can't decode byte 0x8b in position 1`` —
0x8b это второй байт gzip-магии ``1f 8b``. Значит тело дошло до маскера уже
сжатым:

1. ``order`` в реестре инвертирован из-за LIFO-семантики ``add_middleware``
   (``user_middleware.insert(0, ...)``): **высокий order = внешний**.
2. ``gzip`` стоял на ``order=560`` — то есть ВНУТРИ ``data_masking`` (580)
   и ``pii_masking_response`` (700).
3. GZip сжимал JSON ≥ ``gzip_minimum_size`` и выставлял ``Content-Encoding``.
4. ``DataMaskingMiddleware`` снаружи подавлял start, собирал сжатые байты и
   падал на ``raw.decode("utf-8")``.
5. Fail-closed fallback возвращал plain-JSON заглушку, но ``new_headers``
   копировал заголовки исходного ответа **включая ``content-encoding: gzip``**,
   заменяя только ``content-length``.

Инвариант, который охраняют тесты ниже: **сжатие — последнее преобразование
тела ответа**, поэтому обязано быть внешним любого middleware, переписывающего
body. Сами маскеры дополнительно не трогают уже закодированные ответы, чтобы
инвариант не зависел от порядка регистрации (в т.ч. для middleware из
плагинов).
"""

from __future__ import annotations

import gzip
import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.entrypoints.middlewares.brotli_compression import (
    BrotliCompressionMiddleware,
)
from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware
from src.backend.entrypoints.middlewares.gzip_compression_excluding import (
    GZipCompressionExcludingMiddleware,
)
from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry
from src.backend.entrypoints.middlewares.setup_middlewares import build_default_registry

GZIP_ACCEPT = [(b"accept-encoding", b"gzip, deflate, br")]

#: Тело заметно больше gzip_minimum_size (500), как в реальном дефекте.
_BIG_EMAIL_BODY = json.dumps(
    {"items": [{"email": f"user{i}@bank.example", "id": i} for i in range(40)]}
).encode()


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    return {"type": "http.request", "body": b"", "more_body": False}


async def _drive(
    app: ASGIApp, *, path: str = "/api/v1/items", headers=None
) -> list[Message]:
    """Прогоняет HTTP-scope через ``app`` и собирает исходящие сообщения."""
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": list(headers if headers is not None else GZIP_ACCEPT),
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, _receive, send)
    return sent


def _header_of(messages: list[Message], name: str) -> bytes | None:
    """Значение заголовка из первого ``http.response.start``."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            for key, value in msg.get("headers", []):
                if key.lower() == name.lower().encode("latin-1"):
                    return value
    return None


def _body_of(messages: list[Message]) -> bytes:
    """Склеенное тело из всех ``http.response.body``."""
    return b"".join(
        msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"
    )


# ─────────────────────────── 1. Порядок в реестре ───────────────────────────


def _built_registry() -> MiddlewareRegistry:
    """Реальный реестр built-in middleware с замоканными settings."""
    real_registry = MiddlewareRegistry()
    with (
        patch(
            "src.backend.entrypoints.middlewares.registry.MiddlewareRegistry",
            return_value=real_registry,
        ),
        patch(
            "src.backend.core.config.settings.settings",
            MagicMock(
                secure=MagicMock(
                    cors_origins=["*"],
                    cors_allow_credentials=True,
                    cors_allow_methods=["GET"],
                    cors_allow_headers=["*"],
                    allowed_hosts=["*"],
                ),
                app=MagicMock(
                    compression_brotli=True,
                    brotli_minimum_size=100,
                    brotli_quality=4,
                    gzip_minimum_size=500,
                    gzip_compresslevel=6,
                    title="test",
                ),
            ),
        ),
    ):
        build_default_registry()
    return real_registry


def test_compression_is_registered_outermost_of_every_body_rewriter() -> None:
    """Сжатие обязано иметь order выше всех переписывающих body middleware.

    Из-за LIFO-семантики ``add_middleware`` высокий order = внешний, то есть
    выполняется последним на response-пути и получает уже финальное тело.
    """
    orders = {spec.name: spec.order for spec in _built_registry().specs()}

    body_rewriters = [
        name
        for name in ("data_masking", "pii_masking_response", "response_cache")
        if name in orders
    ]
    assert body_rewriters, "ожидались body-rewriting middleware в реестре"

    for name in ("gzip", "brotli"):
        assert name in orders, f"{name} не зарегистрирован"
        for rewriter in body_rewriters:
            assert orders[name] > orders[rewriter], (
                f"{name} (order={orders[name]}) должен быть ВНЕШНЕ "
                f"{rewriter} (order={orders[rewriter]}): иначе маскер "
                f"получит сжатые байты"
            )


def test_brotli_is_outermost_so_it_prefers_over_gzip() -> None:
    """Brotli регистрируется выше gzip (920 > 900) — предпочтительнее."""
    orders = {spec.name: spec.order for spec in _built_registry().specs()}
    assert orders["brotli"] > orders["gzip"]


# ─────────────── 2. DataMaskingMiddleware: pass-through encoded ───────────────


async def test_data_masking_passes_through_pre_encoded_response() -> None:
    """Уже закодированный ответ пробрасывается без изменений.

    Регрессия исходного дефекта: маскер получал gzip-байты, падал на
    ``decode("utf-8")`` и подменял ответ fail-closed заглушкой, сохранив
    заголовок ``Content-Encoding: gzip``.
    """
    encoded = gzip.compress(_BIG_EMAIL_BODY)

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-encoding", b"gzip"),
                    (b"content-length", str(len(encoded)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": encoded, "more_body": False})

    messages = await _drive(DataMaskingMiddleware(downstream))

    assert messages[0]["type"] == "http.response.start", "start обязан уйти первым"
    assert _header_of(messages, "content-encoding") == b"gzip"
    assert _body_of(messages) == encoded, "сжатое тело должно уйти байт в байт"
    assert b"response_masking_failed" not in _body_of(messages)
    # Заглушка не должна подменять ответ.
    assert json.loads(gzip.decompress(_body_of(messages)))["items"]


@pytest.mark.parametrize("encoding", ["gzip", "br", "deflate", "identity"])
async def test_data_masking_skips_any_content_encoding(encoding: str) -> None:
    """Любой выставленный Content-Encoding отключает маскирование."""
    payload = b"not-json-at-all"

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-encoding", encoding.encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": payload, "more_body": False})

    messages = await _drive(DataMaskingMiddleware(downstream))
    assert _body_of(messages) == payload


async def test_data_masking_still_masks_large_json_body() -> None:
    """Защита от обратной регрессии: fail-closed не должен выключить маскирование.

    Грамотный фикс мог бы решить проблему, просто пропуская любой ответ
    ``Content-Encoding: gzip``. Тогда PII перестала бы маскироваться вовсе —
    для ответов крупнее ``minimum_size`` это тихая дыра в безопасности.
    """

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_BIG_EMAIL_BODY)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BIG_EMAIL_BODY})

    messages = await _drive(DataMaskingMiddleware(downstream), headers=[])
    body = _body_of(messages)

    assert b"response_masking_failed" not in body
    # Маскировка сохраняет домен по дизайну (``u***0@bank.example``),
    # поэтому проверяем исходный email целиком, а не домен.
    assert b"user0@bank.example" not in body, "email не должен утекать в ответе"
    assert b"u***0@bank.example" in body, "ожидалась маска local-части"
    assert json.loads(body)["items"], "структура ответа обязана сохраниться"


# ─────────────────── 3. GZip: не терять response.start ───────────────────────


async def test_gzip_forwards_start_when_response_already_encoded() -> None:
    """Ответ с готовым Content-Encoding должен пройти насквозь.

    Раньше middleware ставил флаг ``started = True``, но сам
    ``http.response.start`` **не отправлял** — ответ уходил без start-сообщения.
    Это нарушение ASGI-контракта: uvicorn рвал соединение без ответа.
    """
    inner_body = gzip.compress(_BIG_EMAIL_BODY)

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-encoding", b"gzip"),
                    (b"content-length", str(len(inner_body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": inner_body})

    messages = await _drive(GZipCompressionExcludingMiddleware(downstream))

    types = [msg["type"] for msg in messages]
    assert types[0] == "http.response.start", (
        f"start обязан быть первым, получено {types}"
    )
    assert _header_of(messages, "content-encoding") == b"gzip"
    assert _body_of(messages) == inner_body, "двойного сжатия быть не должно"


# ───────────────────────── 4. Brotli: без двойного сжатия ────────────────────


async def test_brotli_skips_already_encoded_response() -> None:
    """Brotli не должен сжимать поверх уже закодированного ответа.

    Иначе сжатый поток сжимался бы ещё раз, а ``Content-Encoding``
    перезаписывался на ``br``: клиент декодировал бы поток не тем алгоритмом.
    """
    inner_body = gzip.compress(_BIG_EMAIL_BODY)

    async def downstream(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-encoding", b"gzip"),
                    (b"content-length", str(len(inner_body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": inner_body})

    middleware = BrotliCompressionMiddleware(downstream, minimum_size=500)
    if middleware._brotli is None:  # pragma: no cover - опциональный extra
        pytest.skip("brotli не установлен")

    messages = await _drive(middleware, headers=[(b"accept-encoding", b"gzip, br")])

    assert _header_of(messages, "content-encoding") == b"gzip", (
        "заголовок не должен перезаписываться на br"
    )
    assert _body_of(messages) == inner_body, "тело не должно пережиматься"


# ───────────── 5. Сквозной сценарий в порядке реального реестра ──────────────


async def test_gzip_outer_data_masking_inner_produces_valid_gzip() -> None:
    """Сквозной регресс реального порядка: gzip снаружи, маскер внутри.

    Это точная конфигурация, которая стояла в проде и ломала ответы.
    Ожидание: валидный gzip, который после распаковки содержит
    замаскированные PII, а не заглушку ``response_masking_failed``.
    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_BIG_EMAIL_BODY)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BIG_EMAIL_BODY})

    chain = GZipCompressionExcludingMiddleware(
        DataMaskingMiddleware(app), minimum_size=500, compresslevel=6
    )
    messages = await _drive(chain)

    raw = _body_of(messages)
    assert raw[:2] == b"\x1f\x8b", f"ожидался валидный gzip, получено {raw[:8]!r}"

    decoded = gzip.decompress(raw)
    assert b"response_masking_failed" not in decoded
    assert b"user0@bank.example" not in decoded, "маскирование обязано сохраниться"
    assert b"u***0@bank.example" in decoded
    assert json.loads(decoded)["items"], "данные обязаны дойти до клиента"
    assert int(_header_of(messages, "content-length") or b"0") == len(raw)


async def test_real_registry_order_produces_valid_masked_gzip() -> None:
    """Сквозной регресс: цепочка собирается в порядке РЕАЛЬНОГО реестра.

    Предыдущие тесты фиксируют инварианты по отдельности и один из них
    повторяет корректный порядок руками. Этот тест берёт порядок из
    ``build_default_registry()`` — то есть ровно то, что попадает в
    production, — и проверяет результат целиком. Именно он падал на HEAD.
    """

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(_BIG_EMAIL_BODY)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": _BIG_EMAIL_BODY})

    # Управляющие middleware (auth, tenant, otel, …) на ответ не влияют,
    # поэтому в цепочку попадают только те, что переписывают/сжимают body.
    classes: dict[str, Any] = {
        "gzip": lambda a: GZipCompressionExcludingMiddleware(
            a, minimum_size=500, compresslevel=6
        ),
        "data_masking": DataMaskingMiddleware,
    }
    specs = {spec.name: spec.order for spec in _built_registry().specs()}
    assert set(classes) <= set(specs), "ожидались gzip и data_masking в реестре"

    # apply_to_app итерирует specs по возрастанию order, а add_middleware
    # делает insert(0) → последний зарегистрированный становится внешним.
    # Значит наращивать обёртки надо по возрастанию order: сначала внутренний
    # middleware (data_masking), затем внешний (gzip).
    chain: ASGIApp = app
    for name in sorted(classes, key=lambda n: specs[n]):
        chain = classes[name](chain)

    raw = _body_of(await _drive(chain))

    assert raw[:2] == b"\x1f\x8b", f"ожидался валидный gzip, получено {raw[:8]!r}"
    decoded = gzip.decompress(raw)
    assert b"response_masking_failed" not in decoded
    assert b"user0@bank.example" not in decoded, "маскирование обязано сохраниться"
    assert json.loads(decoded)["items"], "данные обязаны дойти до клиента"


async def test_gzip_outer_data_masking_inner_matches_plain_response_payload() -> None:
    """Сжатый и несжатый ответы несут одни и те же данные."""
    payloads: list[bytes] = []

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": _BIG_EMAIL_BODY})

    chain = GZipCompressionExcludingMiddleware(
        DataMaskingMiddleware(app), minimum_size=500, compresslevel=6
    )
    payloads.append(_body_of(await _drive(chain, headers=GZIP_ACCEPT)))
    payloads.append(_body_of(await _drive(chain, headers=[])))

    assert payloads[0][:2] == b"\x1f\x8b", "с Accept-Encoding ответ сжат"
    assert payloads[1][:2] != b"\x1f\x8b", "без Accept-Encoding ответ не сжат"
    assert gzip.decompress(payloads[0]) == payloads[1], (
        "сжатый ответ должен распаковываться ровно в несжатый"
    )
