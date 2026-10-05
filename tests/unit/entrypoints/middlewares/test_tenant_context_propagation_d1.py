"""F-D1 (CRITICAL): tenant-контекст не доходит до ORM — split-brain ContextVar.

На текущем HEAD доказан разрыв между двумя источниками tenant в одном
HTTP-запросе:

* ``scope['state']['tenant_id']`` заполняется ``TenantMiddleware`` — его
  читают 31 модуль через ``RequestContext``;
* ``core.tenancy._current`` — единственный источник для SQLAlchemy-фильтра
  (``core/tenancy/sqlalchemy_filter.py``) и PostgreSQL RLS
  (``infrastructure/database/rls_listener.py``) — **не заполняется никогда**:
  ``set_tenant()`` вызывается только из ``services/tenancy/facade.py``, а у
  ``TenantFacade`` нет ни одного production-потребителя.

Следствие: ``get_tenant_id()`` возвращает ``''``, и оба защитных слоя
делают ровно ``return``:

    sqlalchemy_filter.py:145-147  →  ``if not tenant_id: return``
    rls_listener.py:80-81         →  ``if tenant is None: return``

То есть заявленная изоляция на уровне БД отсутствует, несмотря на
``rls_postgres_enforce=True``.

Эти тесты фиксируют дефект как ИСПОЛНЯЕМУЮ проверку: до фикса красные,
после — зелёные. Правка middleware меняет публичный контракт
``get_tenant_id()``, который читают 56 вызовов в 39 файлах, поэтому тесты
написаны ДО фикса и служат критерием приёмки.
"""

from __future__ import annotations

import re
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.tenancy import current_tenant, get_tenant_id
from src.backend.entrypoints.middlewares.auth_required import AuthRequiredMiddleware
from src.backend.entrypoints.middlewares.tenant import TenantMiddleware

RESOURCE_PATH = "/api/v1/orders/42"

_AUTH_PRINCIPAL = AuthContext(
    method=AuthMethod.JWT,
    principal="user-of-tenant-a",
    metadata={"tenant_id": "tenant-a"},
)


class _Base(sa.orm.DeclarativeBase):
    """Декларативная база для тестовой сущности.

    Модель обязана быть на уровне модуля: SQLAlchemy резолвит аннотации
    через globals модуля, и объявление внутри функции даёт
    ``MappedAnnotationError`` для ``Mapped[int]``.
    """


class _Order(_Base):
    """Минимальная tenant-aware сущность для проверки ORM-фильтра."""

    __tablename__ = "d1_orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(64))
    title: Mapped[str] = mapped_column(sa.String(64))


def _build_chain(inner: Any) -> Any:
    """Собрать production-цепочку auth → tenant → handler.

    Порядок критичен и подтверждён замером (middleware_actual_order.json):
    ``AuthRequiredMiddleware`` (15) выполняется ВНЕ ``TenantMiddleware`` (26),
    а ``APIKeyMiddleware`` (30) — ВНУТРИ обоих. Поэтому tenant связан в тех
    middleware, которые реально узнают principal'а, и привязку нельзя
    проверять на изолированном ``TenantMiddleware`` — тест обязан гнать
    настоящий порядок.

    Args:
        inner: endpoint-приложение, в котором снимается tenant.

    Returns:
        ASGI-приложение с аутентификацией, заменённой на заглушку.

    """

    class _StubbedAuth(AuthRequiredMiddleware):
        """Auth-middleware с предопределённым principal'ом."""

        def __init__(self, app: Any, ctx: AuthContext | None) -> None:
            super().__init__(app, public_prefixes=())
            self._ctx = ctx

        async def _authenticate(self, scope: Any, receive: Any) -> AuthContext | None:
            return self._ctx

    return _StubbedAuth(TenantMiddleware(inner), _AUTH_PRINCIPAL)


def _scope() -> dict[str, Any]:
    """Собрать ASGI scope с аутентифицированным principal'ом.

    ``state['auth']`` намеренно НЕ пре-сеется: principal' обязан поставить
    сам ``AuthRequiredMiddleware``, иначе он выходит по ветке
    ``existing_auth`` и минует проверяемую привязку tenant'а.

    Returns:
        ASGI scope в виде, как его отдаёт uvicorn.

    """
    state: dict[str, Any] = {}
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
        "headers": [(b"host", b"localhost")],
        "client": ("127.0.0.1", 55555),
        "server": ("localhost", 8000),
        "state": state,
    }


async def _call(app: Any, scope: dict[str, Any]) -> None:
    """Выполнить один ASGI-вызов, проглотив ответ.

    Args:
        app: ASGI-приложение под тестом.
        scope: подготовленный scope.

    """

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        return None

    await app(scope, receive, send)


class TestTenantContextReachesEndpoint:
    """F-D1: хендлер обязан видеть аутентифицированный tenant."""

    @pytest.mark.asyncio
    async def test_authenticated_tenant_visible_in_endpoint(self) -> None:
        """Внутри хендлера ``get_tenant_id()`` возвращает tenant principal'а.

        До фикса возвращает ``''`` — ORM-фильтр и RLS-listener выходят
        по ``return`` и не накладывают НИ ОДНОГО условия.
        """
        observed: dict[str, Any] = {}

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            # Снимок делается в момент исполнения хендлера — это ровно та
            # точка, где ORM отдаёт SELECT и где нужен tenant.
            observed["get_tenant_id"] = get_tenant_id()
            observed["current_tenant"] = current_tenant()
            observed["state_tenant_id"] = scope.get("state", {}).get("tenant_id")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = _build_chain(inner)
        await _call(app, _scope())

        # scope-уровень tenant middleware уже заполняет корректно —
        # это подтверждает, что сломан именно ContextVar, а не резолв.
        assert observed["state_tenant_id"] == "tenant-a"
        assert observed["get_tenant_id"] == "tenant-a", (
            "CRITICAL F-D1: tenant не дошёл до core.tenancy. "
            f"get_tenant_id() вернул {observed['get_tenant_id']!r} при "
            f"state['tenant_id']={observed['state_tenant_id']!r}. "
            "ORM-фильтр и RLS-listener при этом выходят по `return` и "
            "не накладывают условий — кросс-tenant чтение возможно."
        )
        assert observed["current_tenant"] is not None
        assert observed["current_tenant"].tenant_id == "tenant-a"

    @pytest.mark.asyncio
    @pytest.mark.asyncio
    async def test_context_does_not_leak_after_request(self) -> None:
        """После завершения запроса ContextVar обязан быть сброшен.

        Без сброса tenant первого запроса остался бы видимым дальше по
        стеку и для следующего запроса, что хуже отсутствия изоляции:
        доступ получает не свой principal, а чужой. Проверка идёт в той
        же задаче, что и сам запрос, — именно там жил бы «протечший»
        ContextVar.
        """
        seen: list[str] = []

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            seen.append(get_tenant_id())
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = _build_chain(inner)
        await _call(app, _scope())

        assert seen == ["tenant-a"]
        assert get_tenant_id() == "", (
            "tenant предыдущего запроса утек в контекст задачи: "
            f"get_tenant_id() вернул {get_tenant_id()!r} после завершения "
            "запроса. Сброс ContextVar обязателен."
        )


class TestOrmFilterSeesTenant:
    """F-D1: реальное следствие — SQL-фильтр должен сузить выборку."""

    @pytest.mark.asyncio
    async def test_tenant_filter_narrows_query(self) -> None:
        """В tenant-контексте ORM-фильтр добавляет WHERE по tenant_id.

        Проверяется на настоящем SQLAlchemy: если ContextVar пуст, фильтр
        не добавит условий и ``tenant_id`` в SQL отсутствует — это и есть
        заявленная, но отсутствующая изоляция.
        """
        from src.backend.core.tenancy import sqlalchemy_filter as tf

        engine = sa.create_engine("sqlite://")
        tf.apply_tenant_filter()
        _Base.metadata.create_all(engine)

        seen_sql: list[str] = []

        @sa.event.listens_for(engine, "before_cursor_execute")
        def _capture(conn: Any, cursor: Any, statement: str, *a: Any) -> None:
            seen_sql.append(statement)

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            # Запрос идёт из хендлера — того же места, где раньше увидели ''.
            with sa.orm.Session(engine) as session:
                session.execute(sa.select(_Order)).all()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        app = _build_chain(inner)
        await _call(app, _scope())

        select_sql = next((s for s in seen_sql if "d1_orders" in s), "")
        assert select_sql, "SQL не был выполнен — тест не проверил ничего"
        # Проверяем именно WHERE, а не наличие подстроки в SELECT-списке:
        # колонка tenant_id присутствует в любом случае, и такая проверка
        # проходила бы даже при полностью отсутствующей фильтрации.
        where_clause = re.split(r"\bWHERE\b", select_sql, maxsplit=1)
        has_tenant_where = len(where_clause) > 1 and bool(
            re.search(r"tenant_id\s*=", where_clause[1], re.IGNORECASE)
        )
        assert has_tenant_where, (
            "CRITICAL F-D1: SQL-фильтр не наложил условие tenant_id в WHERE. "
            f"Запрос: {select_sql!r}. Значит get_tenant_id() вернул пустую "
            "строку и изоляция на уровне ORM отсутствует."
        )


class TestPrincipalWithoutTenantInMetadata:
    """Второй класс, который adversarial review выделил отдельно.

    ``bind_tenant_from_metadata`` возвращает ``None``, если в metadata нет
    ``tenant_id`` — а у API-key principal'ов там только ``key_id`` и
    ``admin_roles``. Значит привязки не было, ORM-фильтр видел пустую
    строку и не накладывал НИ ОДНОГО условия, хотя ``TenantMiddleware``
    к этому моменту уже проставил ``state['tenant_id'] = "default"``.

    Привязка поэтому делается и в самом TenantMiddleware: к его позиции
    (26) tenant для JWT-пути уже разрешён окончательно.
    """

    @pytest.mark.asyncio
    async def test_api_key_principal_without_tenant_metadata_is_bound(self) -> None:
        """Platform API-key получает tenant из default, а не пустую строку."""
        from src.backend.core.auth import AuthContext, AuthMethod

        no_tenant = AuthContext(
            method=AuthMethod.API_KEY,
            principal="api_key_consumer",
            metadata={"key_id": "k1", "admin_roles": ["admin"]},  # без tenant_id
        )
        observed: dict[str, Any] = {}

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            observed["get_tenant_id"] = get_tenant_id()
            observed["state_tenant_id"] = scope.get("state", {}).get("tenant_id")
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        class _Stub(AuthRequiredMiddleware):
            async def _authenticate(self, scope: Any, receive: Any) -> Any:
                return no_tenant

        app = _Stub(TenantMiddleware(inner), public_prefixes=())
        await _call(app, _scope())

        assert observed["state_tenant_id"] == "default"
        assert observed["get_tenant_id"] == "default", (
            "CRITICAL F-D1: principal без tenant_id в metadata остался без "
            f"привязки — get_tenant_id() вернул {observed['get_tenant_id']!r}, "
            "ORM-фильтр и RLS-listener выходят по return и не накладывают "
            "условий. TenantMiddleware уже разрешил state['tenant_id'], значит "
            "привязка обязана быть и здесь."
        )

    @pytest.mark.asyncio
    async def test_orm_filter_narrows_for_platform_api_key(self) -> None:
        """Тот же случай на уровне SQL: WHERE по tenant_id появляется."""
        import sqlalchemy as sa
        from sqlalchemy.orm import mapped_column

        from src.backend.core.auth import AuthContext, AuthMethod
        from src.backend.core.tenancy import sqlalchemy_filter as tf

        class _B(sa.orm.DeclarativeBase):
            pass

        class _Row(_B):
            __tablename__ = "d1_rows"
            id: Mapped[int] = mapped_column(primary_key=True)
            tenant_id: Mapped[str] = mapped_column(sa.String(64))

        engine = sa.create_engine("sqlite://")
        tf.apply_tenant_filter()
        _B.metadata.create_all(engine)
        seen: list[str] = []

        @sa.event.listens_for(engine, "before_cursor_execute")
        def _cap(conn: Any, cur: Any, statement: str, *a: Any) -> None:
            seen.append(statement)

        no_tenant = AuthContext(
            method=AuthMethod.API_KEY,
            principal="api_key_consumer",
            metadata={"key_id": "k1"},
        )

        async def inner(scope: dict[str, Any], receive: Any, send: Any) -> None:
            with sa.orm.Session(engine) as session:
                session.execute(sa.select(_Row)).all()
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"{}"})

        class _Stub(AuthRequiredMiddleware):
            async def _authenticate(self, scope: Any, receive: Any) -> Any:
                return no_tenant

        await _call(_Stub(TenantMiddleware(inner), public_prefixes=()), _scope())

        sql = next((q for q in seen if "d1_rows" in q), "")
        where = re.split(r"\bWHERE\b", sql, maxsplit=1)
        assert len(where) > 1 and re.search(
            r"tenant_id\s*=", where[1], re.IGNORECASE
        ), (
            f"CRITICAL F-D1: для platform API-key SQL-фильтр не сузил выборку. "
            f"Запрос: {sql!r}"
        )
