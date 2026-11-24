"""Middleware для HTTP-кэширования GET-ответов (cycle 55 pure ASGI).

Добавляет заголовки ETag и Cache-Control к GET-ответам
с Content-Type: application/json. Поддерживает условные
запросы через If-None-Match.

Cycle 55: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с cycle 33-54 (L1 middlewares).

Cycle 55 design: response headers modification через send-wrapper.
3 headers: ETag, Cache-Control, и conditional If-None-Match → 304.

В BaseHTTPMiddleware версии middleware использовал
``response.body_iterator = async_chunk_iterator([body])`` (магический
Starlette API) для restore body. В pure ASGI нет body_iterator —
только suppression + re-send pattern (аналог cycle 54 PII).

Однако cycle 55 ОТЛИЧАЕТСЯ: response НЕ модифицируется (только
headers добавляются). Можно: добавить headers через send-wrapper
(start message), и downstream-consumers получат body как есть
(т.к. body НЕ модифицируется, можно не suppress + re-send).

P2-5 (CODE_AUDIT_2026-11-18): ETag обязан идентифицировать ТЕЛО,
которое реально уходит клиенту. Middleware зарегистрирован на
order=710 — ВНЕШНЕ обоих маскеров (``data_masking`` 580,
``pii_masking_response`` 700), поэтому хеш считается по уже
замаскированным байтам. Раньше (order=520, внутри маскеров) ETag
считался по сырому телу, а клиент получал замаскированное — иденти-
фикатор не соответствовал контенту. Порядок регистрации зафиксирован
тестом ``tests/unit/entrypoints/middlewares/test_etag_masking_order.py``.

Волна 2026-11-20 (аудит prod-readiness, находки 3.1 и 3.2)
------------------------------------------------------------------

1. Политика кэширования. Раньше ``_cache_control()`` жёстко возвращал
   ``public, max-age=N`` для ЛЮБОГО 200 JSON GET, а исходные
   ``Cache-Control``/``ETag`` downstream удалялись. Итог: политика
   endpoint'а (``no-store``) терялась, а персонализированные ответы
   объявлялись публично кэшируемыми (CDN/proxy мог отдать чужой ответ).
   Теперь политика считается одной функцией ``_cache_control()``
   (и для 200, и для 304):

   * ``public`` — ТОЛЬКО явный opt-in endpoint'а И анонимный запрос;
   * персонализированный запрос (``Authorization`` / ``X-API-Key`` /
     ``Cookie`` / ``scope['state']['auth']``) → ``private``;
   * ``Set-Cookie`` в ответе → ``no-store`` (перекрывает opt-in);
   * политика endpoint'а сохраняется; если в ней нет ``max-age`` /
     ``s-maxage`` / ``no-store`` — добавляется ``max-age=N``;
   * без политики endpoint'а → ``private, max-age=N`` (никогда не public).

   ``Vary`` намеренно НЕ используется как замена авторизации: кэш
   разделяется по директивам, а не по заголовкам запроса.

2. Streaming. Раньше тело накапливалось в ``body_chunks`` для ВСЕХ
   ответов, а проверка content-type выполнялась ПОСЛЕ накопления:
   SSE отдавался только после завершения downstream, бесконечный
   поток вешал ответ, большие ответы буферизовались в памяти.
   Теперь решение «кэшировать или нет» принимается на
   ``http.response.start``; не-кэшируемые ответы идут в passthrough
   (без буферизации и без изменения заголовков), а кэшируемые при
   первом признаке потоковости (``more_body=True``) или при превышении
   ``max_body_size`` сбрасывают накопленное и переходят в passthrough
   (ETag в этом случае не считается).
"""

from __future__ import annotations

from dataclasses import dataclass, field

try:
    import xxhash

    _USE_XXHASH = True
except ImportError:
    _USE_XXHASH = False

from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ("ResponseCacheMiddleware",)

#: Лимит тела ответа (в байтах), выше которого ответ не кэшируется (1 MiB).
DEFAULT_MAX_BODY_SIZE = 1024 * 1024

#: Заголовки запроса, делающие его персонализированным.
#: Заголовки, делающие запрос персонализированным.
#:
#: ``x-tenant-id`` — тоже: анонимный запрос с заголовком tenant'а получает
#: tenant-зависимый ответ (``TenantMiddleware`` принимает заголовок, если
#: principal'а нет), и такой ответ нельзя публиковать в общем кэше
#: (shared cache) — иначе один tenant получит данные другого
#: (ЭТАП 3.1, аудит 2026-11-23). ``Vary`` авторизацию не заменяет.
_PERSONAL_HEADERS = frozenset(
    {b"authorization", b"x-api-key", b"cookie", b"x-tenant-id"}
)

#: Заголовки, которые НЕ переносятся в ответ 304: у 304 нет тела, поэтому
#: ни его длины, ни кодировки, ни способа передачи там быть не должно.
#: Все остальные заголовки сохраняются — включая служебные
#: ``x-request-id`` / ``x-correlation-id`` / ``x-tenant-id``: без них
#: условный GET теряет корреляцию логов, а заголовок tenant'а — сам
#: инвариант «tenant один и тот же на всех слоях» (независимое ревью
#: 2026-11-23, MAJOR-2).
_NOT_MODIFIED_EXCLUDED = frozenset(
    {b"content-length", b"content-encoding", b"transfer-encoding"}
)


def _compute_etag(body: bytes) -> str:
    """Вычисляет ETag по байтам ответа (RFC 7232, strong).

    Args:
        body: Байты, которые реально уходят клиенту (после маскирования).

    Returns:
        ETag в кавычках, напр. ``"cb6f2a63f81df718"``.

    """
    if _USE_XXHASH:
        return f'"{xxhash.xxh64(body).hexdigest()}"'
    from src.backend.entrypoints.middlewares._body_hash import etag_hash

    return etag_hash(body)


def _strip_weak_prefix(tag: str) -> str:
    """Убрать префикс ``W/`` из entity-tag.

    Args:
        tag: Значение entity-tag (например ``W/"abc"``).

    Returns:
        Tag без префикса слабости (``"abc"``).

    """
    if tag.startswith("W/"):
        return tag[2:]
    return tag


def _if_none_match_matches(header_value: str, etag: str) -> bool:
    """Сравнить ``If-None-Match`` с ETag ответа (RFC 9110 §13.1.2).

    Поддерживаются все формы, которые обязаны поддерживаться сервером
    (ЭТАП 3.2, аудит 2026-11-23):

    * ``*`` — ресурс существует → условие выполнено (304);
    * список entity-tag через запятую — совпадение любого элемента;
    * слабый тег ``W/"..."`` — сравнивается по СЛАБОЙ функции сравнения
      (RFC 9111 §4.2.2): ``W/"abc"`` совпадает с ``"abc"``.

    Args:
        header_value: Значение заголовка ``If-None-Match``.
        etag: ETag текущего ответа.

    Returns:
        True — условие выполнено (ответ 304).

    """
    value = header_value.strip()
    if value == "*":
        return True
    target = _strip_weak_prefix(etag)
    for candidate in value.split(","):
        candidate = candidate.strip()
        if not candidate:
            continue
        if _strip_weak_prefix(candidate) == target:
            return True
    return False


def _etag_value(scope: Scope, body: bytes) -> str:
    """Сформировать ETag ответа с учётом возможного сжатия.

    Если клиент принимает content-coding (gzip/br), тело может быть сжато
    ВНЕШНИМ middleware'ом (``gzip`` order=900, ``brotli`` order=920 — внешние
    к ``response_cache`` order=710) → переданные байты не равны байтам
    identity-представления, по которым считается ETag. RFC 9111 §4.1 требует,
    чтобы сильный валидатор идентифицировал именно переданное представление,
    поэтому в этом случае ETag слабый (``W/"..."``) — RFC 9111 §4.2.2
    (слабый валидатор применим к семантически эквивалентным представлениям,
    каким является content-coding).

    Различение вариантов по кодировке обеспечивают middleware'и сжатия:
    они проставляют ``Vary: Accept-Encoding`` (ЭТАП 3.3).

    Args:
        scope: ASGI scope (источник ``Accept-Encoding``).
        body: Байты тела ответа (identity-представление).

    Returns:
        ETag в кавычках (с ``W/``-префиксом, если ответ может быть сжат).

    """
    digest = _compute_etag(body)
    accept_encoding = _get_header_value(scope, b"accept-encoding").lower()
    if "gzip" in accept_encoding or "br" in accept_encoding:
        return f"W/{digest}"
    return digest


def _is_personalized(scope: Scope) -> bool:
    """Определяет, персонализирован ли запрос.

    Персонализация = заголовки ``authorization`` / ``x-api-key`` /
    ``cookie`` в ``scope['headers']`` ИЛИ наличие ``scope['state']['auth']``.

    ВАЖНО (независимое ревью 2026-11-23, MINOR-1): проверка выполняется
    ЛЕНИВО, в момент формирования ответа, а не на входе в middleware.
    ``auth_required`` (order 620) и ``api_key`` (order 110) стоят ВНУТРИ
    ``response_cache`` (order 710) → на входе ``scope['state']['auth']``
    ещё не установлен, и такой источник персонализации был недостижим.
    К моменту ответа principal уже в state.

    Args:
        scope: ASGI scope.

    Returns:
        True — ответ содержит пользовательские данные и не должен быть
        публично кэшируемым.

    """
    for header_name, _header_value in scope.get("headers", []):
        if header_name.lower() in _PERSONAL_HEADERS:
            return True
    state = scope.get("state") or {}
    return "auth" in state


def _drop_headers(
    headers: list[tuple[bytes, bytes]], names: tuple[bytes, ...]
) -> list[tuple[bytes, bytes]]:
    """Копия списка заголовков без указанных имён (без учёта регистра).

    Args:
        headers: Исходные заголовки ответа.
        names: Имена заголовков, которые нужно убрать.

    Returns:
        Новый список заголовков.

    """
    return [(key, value) for key, value in headers if key.lower() not in names]


@dataclass
class _ResponseState:
    """Состояние проксирования ответа внутри одного запроса.

    Attributes:
        mode: ``collect`` — тело копится; ``passthrough`` — тело идёт
            клиенту как есть; ``done`` — ответ уже отправлен.
        start: Оригинальное сообщение ``http.response.start``.
        status: HTTP-статус ответа.
        headers: Оригинальные заголовки ответа.
        endpoint_policy: Значение ``Cache-Control``, заданное endpoint'ом.
        set_cookie: True, если в ответе есть ``Set-Cookie``.
        chunks: Накопленные чанки тела.

    """

    mode: str = "collect"
    start: Message | None = None
    status: int = 200
    headers: list[tuple[bytes, bytes]] = field(default_factory=list)
    endpoint_policy: str = ""
    set_cookie: bool = False
    chunks: list[bytes] = field(default_factory=list)


class ResponseCacheMiddleware:
    """Pure ASGI middleware: HTTP-кэширование GET-ответов через ETag (cycle 55).

    Args:
        app: ASGI-приложение.
        max_age: TTL в секундах для Cache-Control.
        max_body_size: Максимальный размер тела ответа (в байтах), при
            котором ответ ещё кэшируется. Большие ответы отдаются в
            passthrough (без ETag).

    """

    def __init__(
        self,
        app: ASGIApp,
        max_age: int = 60,
        max_body_size: int = DEFAULT_MAX_BODY_SIZE,
    ) -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            max_age: TTL в секундах для Cache-Control.
            max_body_size: Максимальный размер кэшируемого тела (байт).

        """
        self.app = app
        self._max_age = max_age
        self._max_body_size = max_body_size

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Process HTTP caching for GET responses.

        Args:
            scope: ASGI scope.
            receive: ASGI receive callable.
            send: ASGI send callable.

        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Non-GET requests skip caching.
        if scope.get("method", "") != "GET":
            await self.app(scope, receive, send)
            return

        state = _ResponseState()

        async def send_wrapper(message: Message) -> None:
            """Перехватывает ответ downstream: сбор тела или passthrough."""
            if state.mode == "done":
                return
            if state.mode == "passthrough":
                await send(message)
                return

            if message["type"] == "http.response.start":
                if not self._inspect_start(message, state):
                    # Passthrough — отдаём ответ как есть: без буферизации
                    # и без изменения заголовков.
                    state.mode = "passthrough"
                    await send(message)
                return

            if message["type"] == "http.response.body":
                chunk = message.get("body", b"")
                more = bool(message.get("more_body", False))
                if more:
                    # Потоковый ответ → сброс накопленного и passthrough.
                    state.chunks.append(chunk)
                    await self._flush(send, state)
                    state.mode = "passthrough"
                    return
                body_len = sum(len(part) for part in state.chunks) + len(chunk)
                if body_len > self._max_body_size:
                    # Тело больше лимита → сброс + passthrough (ETag не считаем).
                    await self._flush(send, state)
                    state.mode = "passthrough"
                    await send(message)
                    return
                state.chunks.append(chunk)
                if not more:
                    await self._finalize(send, scope, state)
                    state.mode = "done"
                return

            await send(message)

        await self.app(scope, receive, send_wrapper)

        # Downstream не прислал финальное тело — ответ обязан быть начат
        # и завершён (ASGI-контракт). Если ответа не было вовсе —
        # fabricating'а нет: ошибка остаётся ошибкой приложения.
        if state.mode == "collect" and state.start is not None:
            await self._finalize(send, scope, state)
            state.mode = "done"

    def _inspect_start(self, message: Message, state: _ResponseState) -> bool:
        """Разбирает ``http.response.start`` и решает, кэшируется ли ответ.

        Кэшируется только 200 JSON-ответ без ``Content-Encoding`` и без
        ``Content-Length`` больше ``max_body_size``.

        Args:
            message: Сообщение ``http.response.start``.
            state: Состояние ответа (заполняется по ходу).

        Returns:
            True — ответ кэшируется (ETag + Cache-Control), False — passthrough.

        """
        state.start = message
        state.status = int(message.get("status", 200))
        state.headers = list(message.get("headers", []))
        content_type = ""
        content_encoding = ""
        content_length: int | None = None
        for key, value in state.headers:
            name = key.lower()
            if name == b"content-type":
                content_type = value.decode("latin-1", errors="replace")
            elif name == b"content-encoding":
                content_encoding = value.decode("latin-1", errors="replace")
            elif name == b"content-length":
                try:
                    content_length = int(value.decode("latin-1"))
                except ValueError:
                    content_length = None
            elif name == b"cache-control":
                state.endpoint_policy = value.decode("latin-1", errors="replace")
            elif name == b"set-cookie":
                state.set_cookie = True

        has_encoding = content_encoding.strip().lower() not in ("", "identity")
        return (
            state.status == 200
            and "application/json" in content_type
            and not has_encoding
            and (content_length is None or content_length <= self._max_body_size)
        )

    @staticmethod
    async def _flush(send: Send, state: _ResponseState) -> None:
        """Сбрасывает накопленное тело клиенту (original start + чанки).

        Args:
            send: ASGI send callable.
            state: Состояние ответа.

        """
        if state.start is None:
            return
        await send(state.start)
        for chunk in state.chunks:
            await send({"type": "http.response.body", "body": chunk, "more_body": True})

    async def _finalize(self, send: Send, scope: Scope, state: _ResponseState) -> None:
        """Финализирует кэшируемый ответ: 304 (условный GET) или 200 с ETag.

        Args:
            send: ASGI send callable.
            scope: ASGI scope (источник ``If-None-Match`` и признака
                персонализации — она проверяется именно здесь, когда
                ``scope['state']['auth']`` уже установлен).
            state: Состояние ответа.

        """
        personalized = _is_personalized(scope)
        policy = self._cache_control(
            state.endpoint_policy, personalized, state.set_cookie
        )
        body = b"".join(state.chunks)

        if not body:
            # Пустое тело — ETag строить не по чему, но ответ обязан быть
            # начат И завершён (ASGI-контракт: иначе uvicorn пишет
            # «ASGI callable returned without completing response»).
            headers = _drop_headers(state.headers, (b"etag", b"cache-control"))
            headers.append((b"cache-control", policy.encode("latin-1")))
            await send(
                {
                    "type": "http.response.start",
                    "status": state.status,
                    "headers": headers,
                }
            )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        etag = _etag_value(scope, body)

        # Cycle 55: If-None-Match check (RFC 9110 §13.1.2: ``*``, список
        # тегов и слабое сравнение — ЭТАП 3.2).
        if_none_match = _get_header_value(scope, b"if-none-match")
        if if_none_match and _if_none_match_matches(if_none_match, etag):
            # 304 Not Modified: тело пустое, политика Cache-Control —
            # та же, что у 200 (единый код расчёта). Заголовки ответа
            # сохраняются, кроме тех, что описывают тело (у 304 тела нет);
            # служебные x-request-id / x-correlation-id / x-tenant-id остаются
            # — иначе условный GET теряет корреляцию логов и заголовок
            # tenant'а (независимое ревью 2026-11-23, MAJOR-2).
            headers = [
                (key, value)
                for key, value in state.headers
                if key.lower() not in _NOT_MODIFIED_EXCLUDED
            ]
            headers = [
                (key, value)
                for key, value in headers
                if key.lower() not in (b"etag", b"cache-control")
            ]
            headers.append((b"etag", etag.encode("latin-1")))
            headers.append((b"cache-control", policy.encode("latin-1")))
            await send(
                {"type": "http.response.start", "status": 304, "headers": headers}
            )
            await send({"type": "http.response.body", "body": b"", "more_body": False})
            return

        headers = _drop_headers(state.headers, (b"etag", b"cache-control"))
        headers.append((b"etag", etag.encode("latin-1")))
        headers.append((b"cache-control", policy.encode("latin-1")))
        await send(
            {"type": "http.response.start", "status": state.status, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body, "more_body": False})

    def _cache_control(
        self, endpoint_policy: str, personalized: bool, has_set_cookie: bool
    ) -> str:
        """Вычисляет заголовок ``Cache-Control`` (единый код для 200 и 304).

        Args:
            endpoint_policy: Значение ``Cache-Control``, заданное endpoint'ом.
            personalized: True — запрос персонализирован (auth/cookie).
            has_set_cookie: True — в ответе есть ``Set-Cookie``.

        Returns:
            Значение заголовка ``Cache-Control``.

        """
        if has_set_cookie:
            # Set-Cookie в ответе → кэшировать нельзя (персонализация).
            return "no-store"

        if not endpoint_policy.strip():
            # Без политики endpoint'а — только private: public допустим
            # лишь при явном opt-in endpoint'а (и для анонимных запросов).
            return f"private, max-age={self._max_age}"

        directives = [
            part.strip() for part in endpoint_policy.split(",") if part.strip()
        ]
        if personalized:
            # Персонализированный ответ не должен попадать в ОБЩИЙ кэш
            # (CDN/proxy): директива ``public`` запрещена, ``s-maxage``
            # (хранить в shared cache) выбрасывается, а ``private``
            # добавляется, если его не было (независимое ревью 2026-11-23,
            # MINOR-2).
            directives = [
                part for part in directives if not part.lower().startswith("s-maxage")
            ]
            directives = [
                "private" if part.lower() == "public" else part for part in directives
            ]
            if not any(part.lower() == "private" for part in directives):
                directives.insert(0, "private")
        names = {part.split("=", 1)[0].strip().lower() for part in directives}
        if not names & {"max-age", "s-maxage", "no-store"}:
            directives.append(f"max-age={self._max_age}")
        return ", ".join(directives)


def _get_header_value(scope: Scope, name: bytes) -> str:
    """Извлекает header из ASGI scope (cycle 43 helper)."""
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return ""
    return ""
