"""Регресс P2-5 (CODE_AUDIT_2026-11-18): ETag считался по ДО-маскирования тела.

Дефект
------
``ResponseCacheMiddleware`` был зарегистрирован на ``order=520`` — ВНУТРИ
обоих маскеров (``data_masking`` 580, ``pii_masking_response`` 700). Из-за
LIFO-семантики ``add_middleware`` (высокий order = внешний) middleware
отрабатывал на response-пути ПЕРВЫМ и видел СЫРОЕ тело::

    ETag = hash(raw) != hash(delivered)

Клиент при этом получал ЗАМАСКИРОВАННОЕ тело. Итог: идентификатор не
соответствовал контенту — условный GET отдавал «не то» тело, CDN/браузер
кэшировал по чужому идентификатору, а два разных PII в одном ответе давали
один и тот же ETag.

Инвариант после фикса
----------------------
ETag = хеш байтов, которые РЕАЛЬНО уходят клиенту (после маскирования, до
transfer-кодирования сжатия). ``response_cache`` зарегистрирован на
``order=710`` — ВНЕШНЕ маскеров и ВНУТРЕННЕ сжатия (900/920).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.entrypoints.middlewares.data_masking import DataMaskingMiddleware
from src.backend.entrypoints.middlewares.pii_masking_response import (
    PIIMaskingResponseMiddleware,
)
from src.backend.entrypoints.middlewares.registry import MiddlewareRegistry
from src.backend.entrypoints.middlewares.response_cache import (
    ResponseCacheMiddleware,
    _compute_etag,
)
from src.backend.entrypoints.middlewares.setup_middlewares import build_default_registry

#: Тело ответа с PII — маскеры обязаны его изменить.
_RAW_BODY = b'{"email": "alice@example.com", "id": 1}'

#: Путь вне маскирования (канон — ``data_masking.MASKING_EXEMPT_PATHS``).
_EXEMPT_PATH = "/openapi.json"

#: Путь под маскированием.
_MASKED_PATH = "/api/v1/items"


async def _receive() -> Message:  # pragma: no cover - тело запроса не читается
    return {"type": "http.request", "body": b"", "more_body": False}


def _json_app(body: bytes) -> ASGIApp:
    """ASGI-приложение, отдающее заданное JSON-тело."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        await send(
            {
                "type": "http.response.start",
                "status": 200,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("latin-1")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    return app


async def _drive(
    app: ASGIApp,
    *,
    path: str = _MASKED_PATH,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> list[Message]:
    """Прогоняет HTTP-scope через ``app`` и собирает исходящие сообщения."""
    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": path,
        "headers": list(headers or []),
    }
    sent: list[Message] = []

    async def send(message: Message) -> None:
        sent.append(message)

    await app(scope, _receive, send)
    return sent


def _header_of(messages: list[Message], name: str) -> bytes | None:
    """Значение заголовка из ``http.response.start``."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            for key, value in msg.get("headers", []):
                if key.lower() == name.lower().encode("latin-1"):
                    return value
    return None


def _status_of(messages: list[Message]) -> int | None:
    """HTTP-статус из ``http.response.start``."""
    for msg in messages:
        if msg["type"] == "http.response.start":
            return int(msg.get("status", 200))
    return None


def _body_of(messages: list[Message]) -> bytes:
    """Склеенное тело ответа."""
    return b"".join(
        msg.get("body", b"") for msg in messages if msg["type"] == "http.response.body"
    )


def _types_of(messages: list[Message]) -> list[str]:
    """Типы отправленных сообщений."""
    return [msg["type"] for msg in messages]


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


def _orders() -> dict[str, int]:
    """Карта ``{имя middleware: order}`` реального реестра."""
    return {spec.name: spec.order for spec in _built_registry().specs()}


def test_response_cache_registered_outer_of_maskers() -> None:
    """ETag обязан считаться ПОСЛЕ маскирования → response_cache ВНЕШНЕ маскеров.

    Из-за LIFO-семантики ``add_middleware`` высокий order = внешний, то есть
    выполняется последним на response-пути и получает уже финальное тело.
    """
    orders = _orders()

    for masker in ("data_masking", "pii_masking_response"):
        assert orders["response_cache"] > orders[masker], (
            f"response_cache (order={orders['response_cache']}) должен быть "
            f"ВНЕШНЕ {masker} (order={orders[masker]}): иначе ETag считается "
            f"по телу ДО маскирования, а клиент получает ПОСЛЕ"
        )


def test_response_cache_stays_inner_of_compression() -> None:
    """Сжатие остаётся последним преобразованием тела (order 900/920)."""
    orders = _orders()

    for compressor in ("gzip", "brotli"):
        assert orders[compressor] > orders["response_cache"], (
            f"{compressor} (order={orders[compressor]}) должен быть ВНЕШНЕ "
            f"response_cache (order={orders['response_cache']})"
        )


# ─────────────────── 2. Сквозной сценарий в порядке реестра ──────────────────

#: Фабрики middleware, участвующих в цепочке ответа.
_CHAIN: dict[str, Any] = {
    "response_cache": lambda app: ResponseCacheMiddleware(app, max_age=60),
    "data_masking": DataMaskingMiddleware,
    "pii_masking_response": PIIMaskingResponseMiddleware,
}


def _build_chain(app: ASGIApp, names: tuple[str, ...]) -> ASGIApp:
    """Собирает цепочку в порядке РЕАЛЬНОГО реестра.

    ``apply_to_app`` итерирует spec'ы по возрастанию order, а
    ``add_middleware`` делает ``insert(0)`` → последний зарегистрированный
    становится внешним. Значит наращивать обёртки надо по возрастанию order.
    """
    specs = _orders()
    assert set(names) <= set(specs), "ожидались middleware в реестре"

    chain: ASGIApp = app
    for name in sorted(names, key=lambda n: specs[n]):
        chain = _CHAIN[name](chain)
    return chain


@pytest.fixture
def pii_masking_on() -> Any:
    """Гарантирует включённый ``pii_masking_response`` (feature-flag)."""
    with patch.object(
        PIIMaskingResponseMiddleware, "_is_enabled", staticmethod(lambda: True)
    ):
        yield


@pytest.mark.unit
class TestEtagIdentifiesDeliveredBody:
    """ETag = хеш байтов, которые реально уходят клиенту."""

    async def test_etag_matches_delivered_body(self, pii_masking_on: Any) -> None:
        """ETag идентифицирует ОТДАВАЕМОЕ (замаскированное) тело."""
        chain = _build_chain(
            _json_app(_RAW_BODY),
            ("response_cache", "data_masking", "pii_masking_response"),
        )

        messages = await _drive(chain)

        delivered = _body_of(messages)
        etag = (_header_of(messages, "etag") or b"").decode("latin-1")

        assert etag, "ETag обязан быть выдан"
        assert delivered != _RAW_BODY, "маскирование обязано было изменить тело"
        assert etag == _compute_etag(delivered), (
            "ETag должен совпадать с хешем ОТДАВАЕМОГО тела, а не сырого"
        )
        assert etag != _compute_etag(_RAW_BODY), (
            "ETag не должен совпадать с хешем тела ДО маскирования"
        )

    async def test_same_raw_body_different_delivery_different_etag(
        self, pii_masking_on: Any
    ) -> None:
        """Одинаковое сырое тело, разная выдача → разные ETag.

        Путь вне маскирования отдаёт сырое тело, путь под маскированием —
        замаскированное. Идентификатор обязан различать их, иначе кэш
        (CDN/браузер) отдаст «не то» тело.
        """
        chain = _build_chain(
            _json_app(_RAW_BODY),
            ("response_cache", "data_masking", "pii_masking_response"),
        )

        masked = await _drive(chain, path=_MASKED_PATH)
        exempt = await _drive(chain, path=_EXEMPT_PATH)

        masked_etag = (_header_of(masked, "etag") or b"").decode("latin-1")
        exempt_etag = (_header_of(exempt, "etag") or b"").decode("latin-1")

        assert _body_of(masked) != _body_of(exempt), "тела должны различаться"
        assert masked_etag != exempt_etag, (
            "ETag обязан отражать отдаваемое тело: одинаковый ETag на разных "
            "телах означает, что кэш отдаст «не то» тело"
        )

    async def test_different_pii_yields_different_etag(self) -> None:
        """Разные PII в теле → разные ETag.

        Цепочка из ``response_cache`` + ``data_masking``: маска сохраняет
        отличие (``a***e@`` против ``b***b@``), поэтому ETag обязан различаться.
        """
        chain = _build_chain(
            _json_app(b'{"email": "alice@example.com"}'),
            ("response_cache", "data_masking"),
        )
        other_chain = _build_chain(
            _json_app(b'{"email": "bob@example.com"}'),
            ("response_cache", "data_masking"),
        )

        first = await _drive(chain)
        second = await _drive(other_chain)

        first_etag = (_header_of(first, "etag") or b"").decode("latin-1")
        second_etag = (_header_of(second, "etag") or b"").decode("latin-1")

        assert first_etag != second_etag, "разные PII → разные ETag"
        assert first_etag == _compute_etag(_body_of(first))
        assert second_etag == _compute_etag(_body_of(second))

    async def test_same_body_yields_same_etag(self, pii_masking_on: Any) -> None:
        """Одинаковое тело → одинаковый ETag (детерминизм)."""
        chain = _build_chain(
            _json_app(_RAW_BODY),
            ("response_cache", "data_masking", "pii_masking_response"),
        )

        first = await _drive(chain)
        second = await _drive(chain)

        assert (_header_of(first, "etag") or b"") == (_header_of(second, "etag") or b"")


@pytest.mark.unit
class TestConditionalGet:
    """Условный GET по ETag → 304 без тела."""

    async def test_conditional_get_returns_304_without_body(
        self, pii_masking_on: Any
    ) -> None:
        """If-None-Match с выданным ETag → 304, тело пустое, ответ завершён."""
        chain = _build_chain(
            _json_app(_RAW_BODY),
            ("response_cache", "data_masking", "pii_masking_response"),
        )

        first = await _drive(chain)
        etag = (_header_of(first, "etag") or b"").decode("latin-1")
        assert etag, "первый ответ обязан содержать ETag"

        second = await _drive(
            chain, headers=[(b"if-none-match", etag.encode("latin-1"))]
        )

        assert _status_of(second) == 304
        assert _body_of(second) == b"", "304 не должен содержать тело"
        # ASGI-контракт (волна 35): ответ обязан быть начат И завершён.
        types = _types_of(second)
        assert types[0] == "http.response.start", types
        assert "http.response.body" in types, types
        # Заголовки 304 согласованы с ответом 200.
        assert (_header_of(second, "etag") or b"").decode("latin-1") == etag
        assert _header_of(second, "cache-control") == b"public, max-age=60"

    async def test_conditional_get_by_client_side_etag_returns_304(
        self, pii_masking_on: Any
    ) -> None:
        """304 при If-None-Match, вычисленном клиентом по полученному телу.

        Клиент/CQN перевычисляет ETag по фактически полученным байтам. Если
        сервер считает ETag по сырому телу, такой запрос вернёт 200 с полным
        телом вместо 304 — то есть условный GET перестанет работать.
        """
        chain = _build_chain(
            _json_app(_RAW_BODY),
            ("response_cache", "data_masking", "pii_masking_response"),
        )

        first = await _drive(chain)
        client_etag = _compute_etag(_body_of(first))

        second = await _drive(
            chain, headers=[(b"if-none-match", client_etag.encode("latin-1"))]
        )

        assert _status_of(second) == 304, f"ожидался 304, получено {_status_of(second)}"
        assert _body_of(second) == b""
