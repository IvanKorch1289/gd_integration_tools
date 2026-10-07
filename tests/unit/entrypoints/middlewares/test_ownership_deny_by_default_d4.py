"""D-4 (CRITICAL): object-level авторизация отсутствует полностью.

Переформулировка finding'а после проверки по живому OpenAPI (2026-10-05).
Прежняя формулировка («4 защищённых пути отдаются без object-level проверки,
это IDOR») была НЕВЕРНОЙ: таких путей в приложении нет.

Фактическая картина — хуже и структурно иная. Есть ТРИ независимых
защитных слоя object-level авторизации, и все три инертны:

1. ``TenantResourceIsolationMiddleware`` (``tenant_resource_isolation.py``)
   мёртв дважды:
   * ``register_ownership_checker`` не вызывается НИ ОДНИМ production-сайтом
     (0 совпадений в ``src/``, ``extensions/``, ``routes/``, ``plugins/``,
     ``testkit/``);
   * даже с зарегистрированным checker'ом ветка проверки недостижима:
     0 из 6 ``DEFAULT_PATTERNS`` совпадают с живыми путями. Реальная
     CRUD-поверхность — ``/api/v1/auto/<entity>.<action>`` (414 путей в
     OpenAPI, 443 операции), где идентификатор ресурса передаётся в теле
     запроса, а не в пути. Паттерны написаны под несуществующую
     REST-раскладку ``/api/v1/<entity>/{id}``.

2. ORM tenant-фильтр (``core/tenancy/sqlalchemy_filter.py``) инертен
   из-за F-D1: ``core.tenancy._current`` не заполняется, поэтому
   ``get_tenant_id()`` возвращает ``""``, и слушатель ``do_orm_execute``
   выходит по ``return`` — фильтрация SELECT/UPDATE/DELETE не выполняется.

3. ``require_object_ownership`` (``core/security/object_ownership.py``)
   не используется в production ни разу; вдобавок без ``session_factory``
   и ``explicit_tenant_id`` он сам является fail-open стабом
   (logs only, no fail-closed).

Итог: ни один из 443 REST-эндпоинтов не проходит object-level проверку
владения. Знание чужого ``id`` достаточно для чтения и изменения чужой
записи. Это не «одна небезопасная ветка», а отсутствие механизма.

Тест ниже фиксирует обе части: (а) что защитные ветки существуют и
работают, когда checker зарегистрирован, (б) что они недостижимы на
реальной поверхности. Часть (б) — главный regression-guard: он не даст
кому-либо «подключить checker'ы» и решить, что защита появилась.

Фикс резолва tenant (в этом же коммите): приоритет переведён с
``header → state`` на ``AuthContext.metadata['tenant_id']`` →
``state['tenant_id']``. Заголовок ``X-Tenant-ID`` недоверенный и обязан
совпадать с аутентифицированным tenant'ом, иначе 403 ``tenant_mismatch``.
Без этого подключение checker'ов открывало бы IDOR через подмену
заголовка. До фикса спуфинг был закреплён тестом
``test_tenant_header_priority_over_state``; тест переименован в
``test_tenant_header_mismatch_deny_403`` и теперь закрепляет защиту.
"""

from __future__ import annotations

import re
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.tenant_resource_isolation import (
    DEFAULT_PATTERNS,
    TenantResourceIsolationMiddleware,
)


async def _call(
    app: Any,
    path: str,
    state: dict[str, Any],
    headers: list[tuple[bytes, bytes]] | None = None,
) -> tuple[int, bytes]:
    """Выполнить один ASGI-вызов и вернуть ``(status, body)``.

    Args:
        app: ASGI-приложение под тестом.
        path: запрашиваемый путь.
        state: содержимое ``scope['state']``.
        headers: дополнительные заголовки запроса.

    Returns:
        Кортеж из HTTP-статуса и тела ответа.

    """
    captured: dict[str, Any] = {"status": None, "body": b""}

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.start":
            captured["status"] = message["status"]
        elif message["type"] == "http.response.body":
            captured["body"] = message.get("body", b"")

    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"host", b"localhost"), *(headers or [])],
        "client": ("127.0.0.1", 5555),
        "server": ("localhost", 8000),
        "state": state,
    }
    await app(scope, receive, send)
    status = captured["status"]
    return (0 if status is None else int(status)), captured["body"]


def _passthrough() -> Any:
    """Создать downstream-приложение, отвечающее 204.

    Returns:
        ASGI-приложение.

    """

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    return app


def _recording_checker(result: bool) -> tuple[Any, list[tuple[str, str]]]:
    """Создать ownership checker, запоминающий свои аргументы.

    Args:
        result: значение, которое вернёт checker.

    Returns:
        Кортеж из checker'а и списка зафиксированных вызовов.

    """
    calls: list[tuple[str, str]] = []

    async def checker(resource_id: str, tenant_id: str) -> bool:
        calls.append((resource_id, tenant_id))
        return result

    return checker, calls


class TestDefensiveBranchesExistWhenCheckerRegistered:
    """Слой 1 работает, ЕСЛИ checker зарегистрирован. Это не так."""

    @pytest.mark.asyncio
    async def test_missing_tenant_denies_when_checker_present(self) -> None:
        """С зарегистрированным checker'ом пустой tenant → 403 fail-closed."""
        mw = TenantResourceIsolationMiddleware(_passthrough())
        mw.register_ownership_checker("order", _recording_checker(True)[0])

        status, body = await _call(mw, "/api/v1/orders/999", {})

        assert status == 403
        assert b"tenant identity required" in body

    @pytest.mark.asyncio
    async def test_foreign_resource_denies(self) -> None:
        """Checker вернул ``False`` (ресурс чужой) → 403."""
        mw = TenantResourceIsolationMiddleware(_passthrough())
        mw.register_ownership_checker("order", _recording_checker(False)[0])

        status, body = await _call(mw, "/api/v1/orders/999", {"tenant_id": "tenant-a"})

        assert status == 403
        assert b"resource does not belong to tenant" in body

    @pytest.mark.asyncio
    async def test_owned_resource_passes_with_resolved_tenant(self) -> None:
        """Checker подтвердил владение → запрос проходит, tenant передан."""
        checker, calls = _recording_checker(True)
        mw = TenantResourceIsolationMiddleware(_passthrough())
        mw.register_ownership_checker("order", checker)

        status, _ = await _call(mw, "/api/v1/orders/999", {"tenant_id": "tenant-a"})

        assert status == 204
        assert calls == [("999", "tenant-a")]

    @pytest.mark.asyncio
    async def test_header_can_no_longer_override_authenticated_tenant(self) -> None:
        """D-4 fix: заголовок БОЛЬШЕ НЕ подменяет аутентифицированного tenant'а.

        До фикса приоритет был ``header → state``, и этот тест фиксировал
        уязвимое поведение. Теперь источник истины —
        ``AuthContext.metadata['tenant_id']``, а несовпадение заголовка даёт 403
        и checker не вызывается вовсе.
        """
        checker, calls = _recording_checker(True)
        mw = TenantResourceIsolationMiddleware(_passthrough())
        mw.register_ownership_checker("order", checker)

        status, body = await _call(
            mw,
            "/api/v1/orders/999",
            {"tenant_id": "tenant-a"},
            headers=[(b"x-tenant-id", b"tenant-b")],
        )

        assert status == 403
        assert b"tenant mismatch" in body
        assert calls == [], "checker не должен вызываться при подмене tenant'а"


class TestWithoutCheckerEverythingPasses:
    """Слой 1 в production: checker'ов 0, поэтому ветка проверки мертва."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("path", "resource_type"),
        [
            ("/api/v1/orders/999", "order"),
            ("/api/v1/users/999", "user"),
            ("/api/v1/files/999", "file"),
            ("/api/v1/tenants/999", "tenant"),
            ("/api/v1/accounts/999", "account"),
            ("/api/v1/documents/999", "document"),
        ],
    )
    async def test_no_checker_passes_through(
        self, path: str, resource_type: str
    ) -> None:
        """Без checker'а запрос проходит без 403 — для всех 6 типов ресурсов.

        Пути заданы явно, а не склеены суффиксом: прежний вариант давал
        ``/api/v1/orderss/999`` для типа ``order``, который не совпадает ни с
        одним паттерном, и тест проходил, ничего не проверяя. Поймано мутацией.
        """
        # Guard: путь обязан реально матчиться, иначе тест проверяет не то.
        matched = TenantResourceIsolationMiddleware(_passthrough())._match(path)
        assert matched is not None and matched[0] == resource_type, (
            f"{path} не матчится паттерном типа {resource_type}: {matched}. "
            "Тест потеряет смысл — исправь путь."
        )

        mw = TenantResourceIsolationMiddleware(_passthrough())
        status, _ = await _call(mw, path, {"tenant_id": "tenant-a"})

        assert status == 204, f"{resource_type}: ожидался fail-open pass-through"


class TestPatternsNeverMatchRealSurface:
    """ГЛАВНЫЙ guard: паттерны middleware не совпадают с реальными роутами.

    Даже еслиchecker'ы зарегистрируют, защита не заработает, пока
    ``DEFAULT_PATTERNS`` описывают несуществующую URL-раскладку.
    """

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "D-4: сломанное состояние, зафиксированное намеренно. DEFAULT_PATTERNS "
            "описывают несуществующую раскладку /api/v1/<entity>/{id}, тогда как "
            "реальная поверхность — /api/v1/auto/<entity>.<action>. strict=True означает: "
            "кто-то починит раскладку паттернов → тест даст XPASS и упадёт, forcing "
            "осознанно обновить ожидание и переписать этот finding."
        ),
    )
    def test_default_patterns_are_not_matched_by_any_live_route(self) -> None:
        """Ни один ``DEFAULT_PATTERN`` не совпадает ни с одним путём OpenAPI.

        Проверяется на ЖИВОМ приложении, а не на списке роутов: middleware
        матчится по ``scope['path']`` (путь запроса), поэтому решающим
        источником является фактический набор обслуживаемых путей.
        """
        from src.backend.plugins.composition.app_factory import create_app

        app = create_app()
        openapi_paths = list(app.openapi().get("paths", {}))

        assert openapi_paths, (
            "OpenAPI пуст — тест неинформативен, проверь сборку приложения"
        )

        # D-4: ожидаемое (желаемое) состояние — защитный слой работает,
        # то есть КАЖДЫЙ паттерн находит хотя бы один живой путь.
        # Фактически ни один не находит, поэтому проверка зафиксирована
        # как «сейчас сломан» и обязана падать при исправлении раскладки
        # паттернов — тогда тест переписывается осознанно.
        dead_patterns: list[str] = []
        for pattern in DEFAULT_PATTERNS:
            hits = [p for p in openapi_paths if pattern.pattern.search(p)]
            if not hits:
                dead_patterns.append(pattern.resource_type)

        assert not dead_patterns, (
            "паттерны без единого живого пути: "
            f"{dead_patterns}. Слой object-авторизации не срабатывает ни на одном "
            "из эндпоинтов. Если это осознанно — обнови тест и опиши решение."
        )

    def test_real_surface_is_auto_prefixed_not_path_parameterised(self) -> None:
        """Реальная CRUD-поверхность — ``/api/v1/auto/<entity>.<action>``.

        Документирует причину расхождения: идентификатор ресурса приходит
        в теле запроса, поэтому regex вида ``/api/v1/orders/{id}`` не может
        сработать в принципе.
        """
        from src.backend.plugins.composition.app_factory import create_app

        openapi_paths = list(create_app().openapi().get("paths", {}))

        auto_paths = [p for p in openapi_paths if p.startswith("/api/v1/auto/")]
        assert auto_paths, "ожидалась auto-поверхность действий"

        # Ни один auto-путь не содержит path-параметра идентификатора ресурса.
        id_params = [p for p in auto_paths if re.search(r"/\{[^}]+\}", p)]
        assert not id_params, (
            f"неожиданные path-параметры в auto-поверхности: {id_params[:5]}"
        )
