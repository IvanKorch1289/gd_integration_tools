"""Контракт impersonation в TenantMiddleware (аудит 2026-11-20).

Дефект
------
Capability ``metadata['tenant_impersonation']`` проверялась, но effective
tenant НЕ менялся: ``scope['state']['tenant_id']`` оставался
аутентифицированным, ``_resolve_tenant_id`` тоже отдавал auth-tenant, а
response-заголовок ``X-Tenant-ID`` показывал auth-tenant. Capability была
объявлена, но не действовала — молчаливый no-op, вводящий в заблуждение.

Контракт после фикса
--------------------
1. Capability (``metadata['tenant_impersonation']``) — ЯВНОЕ разрешение
   работать в чужом tenant'е: строка (единственный target) либо
   коллекция строк (whitelist).
2. effective tenant = target-tenant СИНХРОННО в:
   ``scope['state']['tenant_id']``, tenant-контексте (ContextVar → ORM-фильтр
   и PostgreSQL RLS) и response-заголовке ``X-Tenant-ID``.
3. Инвариант: ``state`` == ContextVar == ORM/RLS == response-header.
4. Fail-closed сохранён: capability невалидна (не строка и не коллекция)
   либо target в неё не входит → 403 ``tenant_mismatch``, downstream не
   вызывается.
5. Tenant-контекст очищается после запроса — в том числе после исключения
   downstream; последовательные запросы не загрязняют друг друга.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.tenancy import get_tenant_id
from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

pytestmark = [pytest.mark.unit, pytest.mark.security]

AUTH_TENANT = "tenant-a"
TARGET_TENANT = "tenant-b"
OTHER_TENANT = "tenant-c"
RESOURCE_PATH = "/api/v1/orders/order-42"
LOGGER_NAME = "src.backend.entrypoints.middlewares.tenant"


class _Base(sa.orm.DeclarativeBase):
    """Декларативная база для тестовой tenant-aware сущности.

    Модель обязана быть на уровне модуля: SQLAlchemy резолвит аннотации
    через ``globals()`` модуля, объявление внутри функции даёт
    ``MappedAnnotationError``.
    """


class _Order(_Base):
    """Минимальная tenant-aware сущность для проверки ORM-фильтра."""

    __tablename__ = "impersonation_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(64))
    title: Mapped[str] = mapped_column(sa.String(64))


def _scope(
    *, tenant_header: str | None = None, auth_metadata: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Собрать ASGI scope как его выдаёт uvicorn.

    Args:
        tenant_header: значение заголовка ``X-Tenant-ID`` (недоверенный ввод).
        auth_metadata: ``AuthContext.metadata`` аутентифицированного
            principal'а (``None`` — запрос без аутентификации).

    Returns:
        Готовый ASGI scope.

    """
    headers: list[tuple[bytes, bytes]] = [(b"host", b"localhost")]
    if tenant_header is not None:
        headers.append((b"x-tenant-id", tenant_header.encode("latin-1")))
    state: dict[str, Any] = {}
    if auth_metadata is not None:
        state["auth"] = AuthContext(
            method=AuthMethod.JWT, principal="user-of-tenant-a", metadata=auth_metadata
        )
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": RESOURCE_PATH,
        "raw_path": RESOURCE_PATH.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": headers,
        "client": ("127.0.0.1", 55555),
        "server": ("localhost", 8000),
        "state": state,
    }


def _observer() -> tuple[Any, dict[str, Any]]:
    """Собрать downstream-наблюдатель: снимает tenant со всех слоёв.

    Returns:
        Пара ``(app, observed)`` — ``observed`` заполняется значениями,
        которые видел обработчик.

    """
    observed: dict[str, Any] = {}

    async def inner(scope: Any, receive: Any, send: Any) -> None:
        state = scope.get("state", {}) or {}
        observed["state_tenant_id"] = state.get("tenant_id")
        observed["context_tenant_id"] = get_tenant_id()
        body = json.dumps({"tenant": state.get("tenant_id")}).encode()
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

    return inner, observed


async def _call(app: Any, scope: dict[str, Any]) -> tuple[int, dict[bytes, str], bytes]:
    """Выполнить запрос и вернуть ``(status, headers, body)``.

    Args:
        app: ASGI-приложение под тестом.
        scope: подготовленный scope.

    Returns:
        Кортеж ``(status, headers, body)`` ответа.

    """

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message.get("type") == "http.response.start":
            captured["status"] = message.get("status")
            for k, v in message.get("headers", []):
                captured["headers"][k] = v.decode("latin-1")
        elif message.get("type") == "http.response.body":
            captured["body"] = message.get("body", b"")

    captured: dict[str, Any] = {"status": None, "headers": {}, "body": b""}
    await app(scope, receive, send)
    return captured["status"], captured["headers"], captured["body"]


class TestImpersonationSwitchesTenant:
    """Capability РЕАЛЬНО переключает effective tenant на target."""

    async def test_state_and_context_switch_to_target(self) -> None:
        """``state['tenant_id']`` и ContextVar = target, а не auth-tenant."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, headers, _ = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": TARGET_TENANT,
                },
            ),
        )

        assert status == 200
        assert observed["state_tenant_id"] == TARGET_TENANT
        assert observed["context_tenant_id"] == TARGET_TENANT

    async def test_invariant_state_context_and_header_match(self) -> None:
        """Инвариант одного запроса: state == ContextVar == response-header.

        Именно эту согласованность и фиксирует аудит: раньше capability
        оставляла state и ContextVar на auth-tenant, а заголовок — на том
        же auth-tenant, и подмена tenant'а не происходила вовсе.
        """
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, headers, _ = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": TARGET_TENANT,
                },
            ),
        )

        assert status == 200
        assert observed["state_tenant_id"] == TARGET_TENANT
        assert observed["context_tenant_id"] == observed["state_tenant_id"]
        assert headers[b"x-tenant-id"] == observed["state_tenant_id"]

    async def test_response_header_shows_target(self) -> None:
        """Response-заголовок ``X-Tenant-ID`` = target (иначе слои разойдутся)."""
        app_inner, _ = _observer()
        app = TenantMiddleware(app_inner)

        status, headers, _ = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": TARGET_TENANT,
                },
            ),
        )

        assert status == 200
        assert headers[b"x-tenant-id"] == TARGET_TENANT

    async def test_whitelist_capability_switches_to_allowed_target(self) -> None:
        """Whitelist-коллекция capability разрешает ровно перечисленный tenant."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, headers, _ = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": [OTHER_TENANT, TARGET_TENANT],
                },
            ),
        )

        assert status == 200
        assert observed["state_tenant_id"] == TARGET_TENANT
        assert observed["context_tenant_id"] == TARGET_TENANT
        assert headers[b"x-tenant-id"] == TARGET_TENANT

    async def test_orm_filter_uses_target_tenant(self) -> None:
        """ORM-фильтр (и RLS через него) сужает выборку до target-tenant.

        Проверяется на настоящем SQLAlchemy: если ContextVar остался бы
        auth-tenant'ом, ``WHERE`` содержал бы чужой ``tenant_id`` —
        это ровно та рассинхронизация, которую и фиксирует аудит.
        """
        from src.backend.core.tenancy import sqlalchemy_filter as tf

        engine = sa.create_engine("sqlite://")
        tf.apply_tenant_filter()
        _Base.metadata.create_all(engine)

        seen: list[tuple[str, Any]] = []

        @sa.event.listens_for(engine, "before_cursor_execute")
        def _capture(
            conn: Any, cursor: Any, statement: str, parameters: Any, *a: Any
        ) -> None:
            seen.append((statement, parameters))

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            with sa.orm.Session(engine) as session:
                session.execute(sa.select(_Order)).all()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = TenantMiddleware(inner)
        await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": TARGET_TENANT,
                },
            ),
        )

        select = next(
            (item for item in seen if "impersonation_orders" in item[0]), None
        )
        assert select is not None, "SQL не был выполнен — тест не проверил ничего"
        select_sql, parameters = select
        where_clause = re.split(r"\bWHERE\b", select_sql, maxsplit=1)
        assert len(where_clause) > 1, f"WHERE отсутствует в запросе: {select_sql!r}"
        assert re.search(r"tenant_id\s*=\s*", where_clause[1], re.IGNORECASE), (
            f"tenant-предиката нет в WHERE: {select_sql!r}"
        )
        # Значение tenant'а приходит bind-параметром — проверяем его.
        bound = (
            tuple(parameters)
            if isinstance(parameters, (list, tuple))
            else (parameters,)
            if parameters is not None
            else ()
        )
        assert TARGET_TENANT in bound, (
            "ORM-фильтр не сузил выборку до target-tenant: "
            f"sql={select_sql!r} params={parameters!r}"
        )
        assert AUTH_TENANT not in bound, (
            "ORM-фильтр отфильтровал по auth-tenant вместо target-tenant: "
            f"sql={select_sql!r} params={parameters!r}"
        )

    async def test_audit_warning_is_logged(self, caplog: Any) -> None:
        """Подмена tenant'а логируется WARNING'ом с путём и обоими tenant'ами."""
        app_inner, _ = _observer()
        app = TenantMiddleware(app_inner)

        with caplog.at_level(logging.WARNING, logger=LOGGER_NAME):
            await _call(
                app,
                _scope(
                    tenant_header=TARGET_TENANT,
                    auth_metadata={
                        "tenant_id": AUTH_TENANT,
                        "tenant_impersonation": TARGET_TENANT,
                    },
                ),
            )

        messages = [rec.getMessage() for rec in caplog.records]
        impersonation = [m for m in messages if "IMPERSONATION" in m]
        assert impersonation, f"нет audit-записи об impersonation: {messages!r}"
        record = impersonation[0]
        assert RESOURCE_PATH in record
        assert AUTH_TENANT in record
        assert TARGET_TENANT in record


class TestImpersonationFailClosed:
    """Fail-closed: capability не выдана/невалидна → 403 ``tenant_mismatch``."""

    async def test_mismatch_without_capability_is_rejected(self) -> None:
        """auth tenant-a + чужой заголовок без capability → 403."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, _, body = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT, auth_metadata={"tenant_id": AUTH_TENANT}
            ),
        )

        assert status == 403
        assert json.loads(body)["error"] == "tenant_mismatch"
        assert observed == {}, "downstream не должен быть вызван"

    async def test_capability_for_other_tenant_is_rejected(self) -> None:
        """Capability на другой tenant не разрешает подмену → 403."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, _, body = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": OTHER_TENANT,
                },
            ),
        )

        assert status == 403
        assert json.loads(body)["error"] == "tenant_mismatch"
        assert observed == {}

    async def test_invalid_capability_type_is_rejected(self) -> None:
        """Capability не строка и не коллекция → 403 (fail-closed)."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, _, body = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={"tenant_id": AUTH_TENANT, "tenant_impersonation": 42},
            ),
        )

        assert status == 403
        assert json.loads(body)["error"] == "tenant_mismatch"
        assert observed == {}

    async def test_principal_without_tenant_and_foreign_header_is_rejected(
        self,
    ) -> None:
        """Principal без tenant (API-key) + чужой заголовок → 403."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner)

        status, _, body = await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                # Реальный ``_verify_api_key`` кладёт в metadata только
                # key_id/key_hash/admin_roles — БЕЗ tenant_id.
                auth_metadata={"key_id": "k1", "admin_roles": ["admin"]},
            ),
        )

        assert status == 403
        assert json.loads(body)["error"] == "tenant_mismatch"
        assert observed == {}

    async def test_principal_without_tenant_uses_default(self) -> None:
        """Principal без tenant и без чужого заголовка → default-tenant."""
        app_inner, observed = _observer()
        app = TenantMiddleware(app_inner, default_tenant="default")

        status, headers, _ = await _call(app, _scope(auth_metadata={"key_id": "k1"}))

        assert status == 200
        assert observed["state_tenant_id"] == "default"
        assert observed["context_tenant_id"] == "default"
        assert headers[b"x-tenant-id"] == "default"


class TestTenantContextLifecycle:
    """Контекст очищается после запроса и не течёт между запросами."""

    async def test_context_cleared_after_downstream_exception(self) -> None:
        """Исключение downstream пробрасывается, tenant-контекст сброшен."""
        observed: dict[str, Any] = {}

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            observed["context_tenant_id"] = get_tenant_id()
            observed["state_tenant_id"] = scope.get("state", {}).get("tenant_id")
            raise RuntimeError("downstream failed")

        app = TenantMiddleware(inner)

        with pytest.raises(RuntimeError, match="downstream failed"):
            await _call(
                app,
                _scope(
                    tenant_header=TARGET_TENANT,
                    auth_metadata={
                        "tenant_id": AUTH_TENANT,
                        "tenant_impersonation": TARGET_TENANT,
                    },
                ),
            )

        assert observed["context_tenant_id"] == TARGET_TENANT
        assert observed["state_tenant_id"] == TARGET_TENANT
        assert get_tenant_id() == "", (
            "tenant-контекст не сброшен после исключения downstream: "
            f"get_tenant_id() вернул {get_tenant_id()!r}"
        )

    async def test_sequential_requests_do_not_leak_tenant(self) -> None:
        """Запрос tenant-a, затем tenant-b: контекст второго — b, не a."""
        seen: list[str] = []

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            seen.append(get_tenant_id())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = TenantMiddleware(inner)

        await _call(app, _scope(auth_metadata={"tenant_id": AUTH_TENANT}))
        await _call(app, _scope(auth_metadata={"tenant_id": TARGET_TENANT}))

        assert seen == [AUTH_TENANT, TARGET_TENANT]
        assert get_tenant_id() == "", (
            "tenant-контекст утек за пределы запросов: "
            f"get_tenant_id() вернул {get_tenant_id()!r}"
        )

    async def test_impersonated_request_does_not_leak_into_next_request(self) -> None:
        """После impersonated-запроса следующий запрос не видит чужой tenant."""
        seen: list[str] = []

        async def inner(scope: Any, receive: Any, send: Any) -> None:
            seen.append(get_tenant_id())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = TenantMiddleware(inner)

        await _call(
            app,
            _scope(
                tenant_header=TARGET_TENANT,
                auth_metadata={
                    "tenant_id": AUTH_TENANT,
                    "tenant_impersonation": TARGET_TENANT,
                },
            ),
        )
        await _call(app, _scope(auth_metadata={"tenant_id": AUTH_TENANT}))

        assert seen == [TARGET_TENANT, AUTH_TENANT]
        assert get_tenant_id() == ""
