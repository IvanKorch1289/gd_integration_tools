"""ASGI-приложение для HTTP-contract smoke (вынесено для запуска в Granian).

Зачем
----
Production-рантайм — Granian (ADR-0059), а smoke-инструмент исторически
поднимал только uvicorn. Чтобы тот же HTTP-контракт можно было проверить
на продовом рантайме, приложение вынесено в отдельный модуль: его можно
импортировать и в-process (uvicorn), и в отдельном процессе
(``python -m granian --interface asgi ... tools.checks.http_contract_app:app``).

Приложение собирается с РЕАЛЬНОЙ цепочкой middleware проекта; отключаются
только middleware, требующие внешней инфраструктуры (аутентификация,
IP/role-фильтры). Вместо auth-слоя подставляется минимальный
middleware-двойник: он кладёт в ``scope['state']['auth']`` principal'а с
tenant'ом ``tenant-a`` — ровно то, что делает ``auth_required`` в проде.

API:

* :func:`build_app` — собрать приложение;
* ``app`` — ленивый module-level атрибут (для запуска Granian).
"""

from __future__ import annotations

from typing import Any

#: Пауза между SSE-событиями, секунды (producer работает дольше первого чанка).
SSE_INTERVAL = 0.4

#: Сколько SSE-событий отдаёт producer.
SSE_EVENTS = 3

#: Размер «большого» JSON-тела (больше лимита кэша middleware — 1 MiB).
LARGE_BODY_BYTES = 2 * 1024 * 1024

#: Tenant аутентифицированного principal'а (подставной auth-слой).
AUTH_TENANT = "tenant-a"

#: Tenant в подделанном заголовке — должен быть отклонён.
OTHER_TENANT = "tenant-b"


def build_app() -> Any:
    """Собрать приложение с реальной цепочкой middleware проекта.

    Отключаются только middleware, требующие внешней инфраструктуры
    (аутентификация, IP/role-фильтры) — так же, как в
    ``tests/unit/entrypoints/middlewares/test_streaming_passthrough.py``.
    Вместо auth-слоя подставляется минимальный middleware-двойник: он
    кладёт в ``scope['state']['auth']`` principal'а с tenant'ом
    ``tenant-a`` — ровно то, что делает ``auth_required`` в проде.

    Returns:
        Starlette-приложение.
    """
    from starlette.applications import Starlette
    from starlette.responses import JSONResponse, StreamingResponse
    from starlette.routing import Route

    from src.backend.core.auth import AuthContext, AuthMethod
    from src.backend.entrypoints.middlewares.setup_middlewares import (
        build_default_registry,
    )

    disabled = frozenset(
        {
            "auth_required",
            "api_key",
            "login_step_up",
            "blocked_routes",
            "ip_restriction",
            "trusted_host",
        }
    )

    class _FakeAuthMiddleware:
        """Двойник auth-слоя: кладёт principal'а с tenant'ом ``tenant-a``.

        Ровно то, что делает ``auth_required`` в проде: аутентифицированный
        principal'а с ``metadata['tenant_id']``.
        """

        def __init__(self, app: Any) -> None:
            """Сохранить downstream-приложение.

            Args:
                app: downstream-приложение.
            """
            self.app = app

        async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
            """Подставить principal'а и передать запрос дальше.

            Args:
                scope: ASGI scope.
                receive: ASGI receive.
                send: ASGI send.
            """
            state = scope.setdefault("state", {})
            state["auth"] = AuthContext(
                method=AuthMethod.JWT,
                principal="smoke-user",
                metadata={"tenant_id": AUTH_TENANT},
            )
            await self.app(scope, receive, send)

    async def json_endpoint(request):
        """JSON-ответ без собственной политики кэша."""
        return JSONResponse({"ok": True, "tenant": request.headers.get("x-tenant-id")})

    async def json_no_store_endpoint(request):
        """JSON-ответ с явной политикой ``no-store`` (endpoint-контракт)."""
        response = JSONResponse({"ok": True})
        response.headers["Cache-Control"] = "no-store"
        return response

    async def large_endpoint(request):
        """Большой JSON-ответ (больше лимита кэша middleware)."""
        return JSONResponse({"blob": "x" * LARGE_BODY_BYTES})

    async def sse_endpoint(request):
        """SSE-поток: события с паузами (producer не завершается мгновенно)."""
        import asyncio

        async def events():
            for index in range(SSE_EVENTS):
                yield f"event: tick\ndata: {index}\n\n".encode()
                await asyncio.sleep(SSE_INTERVAL)

        return StreamingResponse(events(), media_type="text/event-stream")

    routes = [
        Route("/json", json_endpoint),
        Route("/json-no-store", json_no_store_endpoint),
        Route("/json-large", large_endpoint),
        Route("/sse", sse_endpoint),
    ]
    app = Starlette(routes=routes)
    registry = build_default_registry()
    overrides = {name: {"enabled": False} for name in disabled}
    registry.apply_to_app(app, route_overrides=overrides)
    # Двойник auth-слоя — ВНЕШНЕ всех остальных (он кладёт principal'а
    # до того, как tenant-middleware разберёт заголовок).
    app.add_middleware(_FakeAuthMiddleware)
    return app


def __getattr__(name: str) -> Any:
    """Ленивая сборка ``app`` (PEP 562).

    Нужна, чтобы процесс smoke не собирал приложение дважды: атрибут
    ``app`` создаётся только при обращении (запуск Granian в отдельном
    процессе).

    Args:
        name: Имя атрибута.

    Returns:
        Собранное ASGI-приложение.

    Raises:
        AttributeError: Если атрибут не ``app``.
    """
    if name == "app":
        application = build_app()
        globals()["app"] = application
        return application
    raise AttributeError(name)
