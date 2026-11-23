"""Tenant middleware — извлекает tenant_id из запроса (cycle 38, pure ASGI).

Wave 6.5a: ``set_correlation_context`` резолвится через DI provider
(``core.di.providers.get_correlation_context_setter_provider``), что
снимает entrypoints → infrastructure layer-violation.

Cycle 38: переписано с ``BaseHTTPMiddleware`` на pure ASGI для
архитектурной консистентности с другими middleware (cycle 33 L1
SecurityHeaders, cycle 36 RequestID, cycle 37 AuthMethodHeader).

SECURITY-P0-002 (аудит 2026-10-01, runtime-доказательство
``artifacts/current_audit/tenant_spoofing.json``)
---------------------------------------------------------
До фикса приоритет tenant_id был ``header > state > default``, что
означало: клиентский ``X-Tenant-ID`` без сверки становился ambient
tenant для всего запроса (в т.ч. через ``tenant_id_var`` →
``get_tenant_id()``), а аутентифицированный tenant из
``AuthContext.metadata['tenant_id']`` вообще не учитывался.

Воспроизведение ДО фикса (реальные production-классы):
    auth tenant-a + ``X-Tenant-ID: tenant-b`` → **HTTP 200**,
    ``state['tenant_id'] == 'tenant-b'`` (ожидалось 403 tenant_mismatch).

Теперь порядок приоритета:
1. ``AuthContext.metadata['tenant_id']`` — единственный доверенный
   источник (аутентифицированный principal, fail-closed);
2. ``scope['state']['tenant_id']`` (если положил inner auth middleware);
3. Header ``X-Tenant-ID`` — доверен ТОЛЬКО когда аутентификации нет;
4. ``default_tenant`` constructor arg.

Если аутентифицированный tenant есть и заголовок с ним расходится —
запрос отклоняется **403 tenant_mismatch**, если только на
аутентифицированном principal не объявлена явная impersonation
capability (``metadata['tenant_impersonation']``).

IMPERSONATION-КОНТРАКТ (аудит 2026-11-20)
------------------------------------------
``metadata['tenant_impersonation']`` — это ЯВНОЕ разрешение principal'а
работать в чужом tenant'е. Кто выдаёт: auth-слой (JWT/SAML/OIDC-провайдер
или admin-контур), записывая ключ в ``AuthContext.metadata``; значение —
строка (единственный target-tenant) либо коллекция строк (whitelist).

Что происходит, когда capability совпадает с target из ``X-Tenant-ID``:

1. ``scope['state']['tenant_id']`` = target;
2. tenant-контекст (``core.tenancy.bind_tenant``) = target — ORM-фильтр
   (``core/tenancy/sqlalchemy_filter.py``) и PostgreSQL RLS видят тот же
   tenant;
3. response-заголовок ``X-Tenant-ID`` = target;
4. WARNING-аудит ``tenant IMPERSONATION path=... authenticated=... target=...``.

Инвариант: ``state`` == ContextVar == ORM/RLS == response-header. До этой
правки capability была объявлена, но НЕ действовала: effective tenant
оставался аутентифицированным, а заголовок показывал auth-tenant —
молчаливый no-op, вводящий в заблуждение.

Fail-closed сохранён: capability невалидна (не строка и не коллекция) либо
target в неё не входит → 403 ``tenant_mismatch`` (тело ответа не содержит
значений tenant). Capability не действует для principal'а БЕЗ
аутентифицированного tenant: такой principal работает в default-tenant, и
заголовок его не расширяет.
"""

from __future__ import annotations

import json
import logging

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.backend.core.auth.auth_context_helpers import (
    extract_tenant_id,
    resolve_impersonation_target,
)
from src.backend.core.di.providers import get_correlation_context_setter_provider
from src.backend.core.tenancy import TenantContext, bind_tenant, unbind_tenant

__all__ = ("TenantMiddleware",)

_TENANT_HEADER = "X-Tenant-ID"
_TENANT_HEADER_BYTES = _TENANT_HEADER.lower().encode("latin-1")

#: Capability имперсонации — см. ``core.auth.auth_context_helpers``:
#: ``IMPERSONATION_METADATA_KEY`` (ключ в ``AuthContext.metadata``) и
#: ``resolve_impersonation_target`` (разбор capability). Здесь capability
#: ПЕРЕКЛЮЧАЕТ effective tenant на target (контракт описан в docstring
#: модуля): state, ContextVar, ORM/RLS и response-header обязаны видеть
#: ОДИН и тот же tenant.


def _authenticated_tenant(scope: Scope) -> str | None:
    """Достать tenant из ``AuthContext.metadata`` — доверенный источник.

    Args:
        scope: ASGI scope.

    Returns:
        Аутентифицированный tenant_id либо ``None``, если аутентификации нет
        **или** principal не заявил tenant (например глобальный API-key).
        Для различения этих случаев используйте :func:`_auth_present`.

    """
    state = scope.get("state")
    if not isinstance(state, dict):
        return None
    auth = state.get("auth")
    if auth is None:
        return None
    return extract_tenant_id(auth)


def _auth_present(scope: Scope) -> bool:
    """Есть ли аутентифицированный principal в scope (независимо от tenant).

    Нужен, чтобы не путать «запрос не аутентифицирован» с «аутентифицирован,
    но tenant не заявлен». Второй случай обязан быть fail-closed
    (аудит 2026-10-01, N-1): реальный ``_verify_api_key`` кладёт в metadata
    только ``key_id``/``key_hash``/``admin_roles`` — **без** ``tenant_id``.

    Args:
        scope: ASGI scope.

    Returns:
        ``True``, если ``state['auth']`` присутствует и не ``None``.
    """
    state = scope.get("state")
    if not isinstance(state, dict):
        return False
    return state.get("auth") is not None


async def _send_tenant_mismatch(send: Send) -> None:
    """Отклонить запрос 403 ``tenant_mismatch`` (fail-closed).

    Тело ответа намеренно НЕ содержит значений tenant: ответ уходит
    неаутентифицированному/неавторизованному клиенту, и подстановка
    идентификаторов раскрывала бы их. Диагностические значения логируются
    вызывающим кодом (см. ``tenant DENY`` WARNING выше по стеку), поэтому
    передавать их сюда было избыточно — параметры удалены 2026-10-16
    (vulture dead-code gate в CI).

    Args:
        send: ASGI send-канал.

    """
    body = json.dumps(
        {
            "error": "tenant_mismatch",
            "detail": (
                "X-Tenant-ID не совпадает с tenant аутентифицированного "
                "principal; impersonation capability не объявлена или не "
                "разрешает этот tenant"
            ),
        }
    ).encode()
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode("latin-1")),
            ],
        }
    )
    await send({"type": "http.response.body", "body": body})


class TenantMiddleware:
    """Pure ASGI middleware для multi-tenant isolation.

    Делает:
    1. Извлекает ``tenant_id`` из request (header → scope.state.tenant_id
       → default).
    2. Устанавливает ``scope['state']['tenant_id']`` (доступно downstream
       как ``request.state.tenant_id``).
    3. Вызывает ``set_correlation_context(tenant_id=...)`` для
       propagation в structlog (все лог-события содержат tenant_id).
    4. Добавляет ``X-Tenant-ID`` в response headers (через send-wrapper).
    5. Переключает effective tenant на target из явной impersonation
       capability (``metadata['tenant_impersonation']``) — синхронно в
       ``scope['state']``, tenant-контексте (ContextVar → ORM/RLS) и
       response-заголовке; без capability — 403 ``tenant_mismatch``.
    """

    def __init__(self, app: ASGIApp, default_tenant: str = "default") -> None:
        """Инициализирует middleware.

        Args:
            app: ASGI-приложение.
            default_tenant: tenant_id если header и state пусты.

        """
        self.app = app
        self._default = default_tenant

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Точка входа ASGI-протокола.

        Non-HTTP scope (``websocket`` / ``lifespan``) пробрасывается
        downstream-приложению без модификации state.

        Cycle 38 retrospective: tenant_id resolution делается
        INSIDE send-wrapper, а не в __call__ — потому что inner
        auth middleware может установить ``state['tenant_id']``
        ПОСЛЕ того, как наш __call__ уже отработал (ASGI outer-to-inner
        ordering). Этот же lesson был в cycle 37 AuthMethodHeader.
        """
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # Request-time pre-fill (integration contract: хендлеры видят
        # tenant из header/default; inner auth middleware перезапишет
        # state['tenant_id'] своим — ASGI ordering это позволяет, т.к.
        # pre-fill идёт ДО вызова downstream). Guard «not in state»:
        # если наружный middleware уже задал tenant — не трогаем.
        state = scope.get("state")
        if not isinstance(state, dict):
            state = {}
            scope["state"] = state

        # SECURITY-P0-002: аутентифицированный tenant авторитетен.
        # AuthRequiredMiddleware (order 620) выполняется РАНЬше TenantMiddleware
        # (order 300) из-за LIFO-семантики add_middleware, поэтому к этому
        # моменту scope['state']['auth'] уже заполнен реальным principal'ом.
        auth_tenant = _authenticated_tenant(scope)
        # Target-tenant явной impersonation capability (None — capability нет).
        # Значение фиксируется ЗДЕСЬ, на request-time: effective tenant
        # решается один раз на запрос, и все слои (state, ContextVar,
        # ORM/RLS, response-header) обязаны видеть одно и то же значение.
        impersonation_target: str | None = None
        if auth_tenant:
            header_value = _get_header(scope, _TENANT_HEADER_BYTES)
            if header_value and header_value != auth_tenant:
                target = resolve_impersonation_target(state.get("auth"), header_value)
                if target is None:
                    logging.getLogger(__name__).warning(
                        "tenant DENY path=%s authenticated=%s requested=%s "
                        "reason=tenant_mismatch",
                        scope.get("path"),
                        auth_tenant,
                        header_value,
                    )
                    await _send_tenant_mismatch(send)
                    return
                # Capability выдана явно → effective tenant = target.
                # Аудит обязателен: подмена tenant'а — привилегированное
                # действие, его нельзя оставить без следа.
                impersonation_target = target
                logging.getLogger(__name__).warning(
                    "tenant IMPERSONATION path=%s authenticated=%s target=%s",
                    scope.get("path"),
                    auth_tenant,
                    target,
                )
            # Авторитетный tenant: заголовок не может его переопределить
            # (кроме явной impersonation capability — см. выше).
            state["tenant_id"] = impersonation_target or auth_tenant
        elif _auth_present(scope):
            # Fail-closed (независимый re-аудит 2026-10-01, N-1): principal
            # аутентифицирован, но tenant не заявлен — так ведёт себя реальный
            # ``_verify_api_key`` (metadata без ``tenant_id``). Прежняя ветка
            # ``elif "tenant_id" not in state`` доверяла здесь заголовку, что
            # давало спуфинг: реальный X-API-Key (principal ``global``) +
            # ``X-Tenant-ID: tenant-b`` → HTTP 200 и чужой tenant в state.
            # Платформенная учётка не принадлежит ни одному tenant — она
            # работает в default, и заголовок её не расширяет.
            header_value = _get_header(scope, _TENANT_HEADER_BYTES)
            if header_value and header_value != self._default:
                logging.getLogger(__name__).warning(
                    "tenant DENY path=%s principal_without_tenant requested=%s "
                    "reason=tenant_not_asserted",
                    scope.get("path"),
                    header_value,
                )
                await _send_tenant_mismatch(send)
                return
            state["tenant_id"] = self._default
        elif "tenant_id" not in state:
            header_value = _get_header(scope, _TENANT_HEADER_BYTES)
            state["tenant_id"] = header_value if header_value else self._default

        # ContextVar на request-path: логи хендлеров несут tenant
        # (response-time set в wrapper обновит после auth).
        try:
            get_correlation_context_setter_provider()(tenant_id=state["tenant_id"])
        except (
            ImportError,
            AttributeError,
            RuntimeError,
            TypeError,
            ValueError,
        ) as corr_exc:
            logging.getLogger(__name__).debug(
                "tenant.correlation_context_skipped: %s", corr_exc
            )

        # Wrap send — response-резолв (impersonation target > header > state
        # [уже с auth] > default) + X-Tenant-ID в response headers.
        send_wrapper = _make_send_wrapper(
            send, scope, self._default, impersonation_target
        )
        # F-D1 (CRITICAL, продолжение): привязка ЗДЕСЬ, а не только в
        # auth-middleware. К этому моменту state['tenant_id'] уже разрешён
        # окончательно для JWT-пути (AuthRequired идёт на позиции 15, то
        # есть выше нас), поэтому ORM-фильтр и RLS-listener видят tenant
        # и для principal'ов БЕЗ tenant_id в metadata — включая
        # API-key, где раньше не bind'илось ничего. Для API-key пути
        # APIKeyMiddleware (позиция 30, вложен в нас) перепривяжет своё
        # значение; порядок bind/unbid остаётся LIFO: A -> T -> K.
        tenant_token = bind_tenant(TenantContext(tenant_id=state["tenant_id"]))
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            unbind_tenant(tenant_token)

    @staticmethod
    def _resolve_tenant_id(
        scope: Scope, default_tenant: str, impersonation_target: str | None = None
    ) -> str:
        """Резолвит tenant_id с авторитетным приоритетом.

        Вызывается INSIDE send-wrapper (cycle 38 retrospective) —
        после того, как inner auth middleware установил
        ``state['tenant_id']``.

        Приоритет (SECURITY-P0-002):
        1. ``impersonation_target`` — effective tenant явной impersonation
           capability (зафиксирован на request-time);
        2. ``AuthContext.metadata['tenant_id']`` (аутентифицированный)
        3. Header ``X-Tenant-ID``
        4. ``scope['state']['tenant_id']``
        5. ``default_tenant``

        Изменение против исходного контракта — ТОЛЬКО пункт 1: при
        наличии аутентифицированного principal'а он авторитетен, и
        подделанный ``X-Tenant-ID`` не может отравить response-заголовок
        и downstream-потребителей (кэш, фронтенд, сервисы). Взаимный
        порядок header/state (пункты 3-4) сохранён без изменений.

        Пункт 1 обязателен для инварианта «state == ContextVar == ORM/RLS
        == response-header»: при impersonation заголовок обязан показывать
        target-tenant, а не аутентифицированный.

        Args:
            scope: ASGI scope.
            default_tenant: tenant_id, если всё остальное пусто.
            impersonation_target: target-tenant из impersonation capability
                (``None`` — capability не применялась).

        Returns:
            Итоговый tenant_id для response-заголовка и correlation-контекста.

        """
        if impersonation_target:
            return impersonation_target
        auth_tenant = _authenticated_tenant(scope)
        if auth_tenant:
            return auth_tenant
        header_value = _get_header(scope, _TENANT_HEADER_BYTES)
        if header_value:
            return header_value
        state = scope.get("state", {})
        if isinstance(state, dict):
            state_tenant = state.get("tenant_id")
            if isinstance(state_tenant, str):
                return state_tenant
        return default_tenant


def _get_header(scope: Scope, name: bytes) -> str | None:
    """Извлекает header из ASGI scope по lowercase bytes-имени.

    Returns:
        Header value (str) или None если не найден.

    """
    for header_name, header_value in scope.get("headers", []):
        if header_name == name:
            try:
                return header_value.decode("latin-1")
            except UnicodeDecodeError:
                return None
    return None


def _make_send_wrapper(
    send: Send,
    scope: Scope,
    default_tenant: str,
    impersonation_target: str | None = None,
) -> Send:
    """Создаёт обёртку вокруг ``send``, добавляющую X-Tenant-ID в start.

    Header добавляется только в ``http.response.start`` сообщение.
    Если downstream уже послал X-Tenant-ID — мы перезаписываем
    (наш tenant source of truth).

    Cycle 38: tenant_id резолвится INSIDE wrapper через
    :meth:`TenantMiddleware._resolve_tenant_id` (после того, как
    inner auth middleware установил state['tenant_id']).

    Также вызывает ``set_correlation_context(tenant_id=...)`` для
    structlog propagation — здесь это безопасно (после __call__ —
    не блокирует request path, только logging payload).

    Args:
        send: исходный ASGI send-канал.
        scope: ASGI scope текущего запроса.
        default_tenant: tenant_id, если всё остальное пусто.
        impersonation_target: target-tenant из impersonation capability —
            приоритет над всеми остальными источниками (инвариант
            «state == ContextVar == ORM/RLS == response-header»).

    Returns:
        Обёртка ``send``, добавляющая заголовок ``X-Tenant-ID``.

    """

    async def send_wrapper(message: Message) -> None:
        if message["type"] == "http.response.start":
            tenant_id = TenantMiddleware._resolve_tenant_id(
                scope, default_tenant, impersonation_target
            )
            tenant_id_bytes = tenant_id.encode("latin-1")

            existing: list[tuple[bytes, bytes]] = list(message.get("headers", []))
            existing = [
                (k, v) for k, v in existing if k.lower() != _TENANT_HEADER_BYTES
            ]
            existing.append((_TENANT_HEADER_BYTES, tenant_id_bytes))
            message["headers"] = existing

            # ContextVar для structlog (только после resolve, чтобы
            # не перезаписать если inner auth middleware ещё не
            # отработал — впрочем, к этому моменту send уже вызван,
            # значит все middlewares отработали).
            try:
                get_correlation_context_setter_provider()(tenant_id=tenant_id)
            except (
                ImportError,
                AttributeError,
                RuntimeError,
                TypeError,
                ValueError,
            ) as corr_exc:
                # cycle-9/D-AUDIT-1001: narrow exceptions + observability.
                # ImportError — provider missing, AttributeError — API
                # change, RuntimeError — DI unavailable, TypeError —
                # wrong tenant_id, ValueError — invalid tenant_id.
                import logging

                logging.getLogger(__name__).debug(
                    "tenant_middleware.correlation_setter_failed",
                    extra={"tenant_id": tenant_id, "error": str(corr_exc)},
                )
        await send(message)

    return send_wrapper
