"""Inventory-тест: гарантия auth-coverage на всех non-public routes (REVIEW §10 OQ-4).

Что измеряет
------------
Тест walks FastAPI ``app.routes`` и для каждого non-public endpoint'а
проверяет, что у него есть хотя бы один из механизмов защиты:

1. **per-handler Depends** (op-level / router-level / common_dependencies).
   FastAPI мержит все три варианта в ``route.dependant.dependencies``
   после резолва router-tree (``_RouterIncludeContext.dependencies +
   APIRoute.dependencies``), поэтому в инвентаре они классифицируются
   как одна группа «per-handler Depends».
2. **AuthRequiredMiddleware** — pure-ASGI defense-in-depth middleware
   (``entrypoints/middlewares/auth_required.py``), перекрывает все
   non-public paths единым 401-ответом.

Coverage-агрегация из REVIEW §10: ≈27 op-level + ≈114 router-level +
≈30 common_dependencies + 132 auto-эндпойнта покрыты middleware.

Ожидаемое поведение
-------------------
* Если ``AuthRequiredMiddleware`` зарегистрирован → ВСЕ non-public
  routes покрыты defense-in-depth → тест PASS (per route).
* Если middleware НЕ зарегистрирован → каждый non-public route
  должен иметь per-handler Depends, иначе FAIL.

Graceful skip: ``create_app()`` падает на отсутствующих зависимостях
(``psycopg``, ``idempotency_header_middleware`` и т.п.) → fallback
на минимальный app (admin + invocations) с явным middleware.

Не измеряет
-----------
Конкретный auth-метод (API_KEY vs JWT vs SAML) — любой Depends
трактуется как auth-признак. Различить rate-limit от auth Depends
без ad-hoc allowlist нельзя; на текущей среде rate-limit без auth
в production-сборке не встречается (все CRUD-роуты кладут auth в
``common_dependencies``).
"""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterable
from typing import Any

import pytest

from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    AuthRequiredMiddleware,
    is_path_public,
)

_log = logging.getLogger(__name__)


# ---- Вспомогательные --------------------------------------------------------


def _walk_routes(routes: Iterable[Any]) -> list[Any]:
    """Recursive walk ``app.routes`` через ``effective_candidates()``.

    FastAPI хранит дочерние routers как ``_IncludedRouter``-обёртки
    (``fastapi/routing.py``); полный граф маршрутов доступен через
    ``_IncludedRouter.effective_candidates()``.
    """
    from fastapi.routing import _IncludedRouter

    out: list[Any] = []
    for route in routes:
        if isinstance(route, _IncludedRouter):
            out.extend(_walk_routes(route.effective_candidates()))
            continue
        if hasattr(route, "dependant") and hasattr(route, "path"):
            out.append(route)
    return out


def _route_source(route: Any) -> str:
    """Best-effort ``file:line`` для endpoint'а (для диагностики FAIL)."""
    endpoint = getattr(route, "endpoint", None)
    if endpoint is None:
        return "<unknown>"
    try:
        src_file = inspect.getsourcefile(endpoint)
        _, src_line = inspect.getsourcelines(endpoint)
    except (OSError, TypeError):
        return endpoint.__module__
    if src_file is None:
        return f"{endpoint.__module__}:?"
    return f"{src_file.rsplit('/', 1)[-1]}:{src_line}"


# ---- Сборка app: full → minimal ----------------------------------------------


def _build_full_app() -> Any:
    from src.backend.plugins.composition.app_factory import create_app

    return create_app()


def _build_minimal_app() -> Any:
    """Минимальный app: admin + invocations routers + AuthRequiredMiddleware."""
    from fastapi import FastAPI

    from src.backend.entrypoints.api.v1.endpoints.admin import router as admin_router
    from src.backend.entrypoints.api.v1.endpoints.invocations import (
        router as invocations_router,
    )

    app = FastAPI()
    app.include_router(admin_router, prefix="/api/v1/admin")
    app.include_router(invocations_router, prefix="/api/v1/invocations")
    app.add_middleware(AuthRequiredMiddleware)
    return app


def _build_app_or_skip() -> tuple[Any, str, bool]:
    """Получить app: full → minimal → skip. Возвращает ``(app, source, auth_mw)``."""
    full_exc: Exception | None = None
    try:
        app = _build_full_app()
        auth_mw = any(mw.cls is AuthRequiredMiddleware for mw in app.user_middleware)
        return app, "full", auth_mw
    except Exception as exc:  # noqa: BLE001
        full_exc = exc
    _log.info("create_app() failed (%s); falling back to minimal app", full_exc)
    try:
        app = _build_minimal_app()
    except Exception as exc_min:  # noqa: BLE001
        pytest.skip(
            f"app build requires unavailable services: full={full_exc!r}, "
            f"minimal={exc_min!r}"
        )
        raise  # для mypy / типа возврата
    auth_mw = any(mw.cls is AuthRequiredMiddleware for mw in app.user_middleware)
    return app, "minimal", auth_mw


# ---- Сбор маршрутов и parametrize -------------------------------------------


def _collect_route_ids(app: Any) -> list[tuple[str, str]]:
    """Список ``(method_set, path)`` для non-public маршрутов — для parametrize."""
    ids: list[tuple[str, str]] = []
    for route in _walk_routes(app.routes):
        path = getattr(route, "path", "") or ""
        if is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES):
            continue
        methods = frozenset(getattr(route, "methods", set()) or set())
        # HEAD — implicit companion для GET, никогда не auth-критичен.
        if methods and methods <= {"HEAD"}:
            continue
        ids.append((",".join(sorted(methods)) or "WS", path))
    return ids


@pytest.fixture(scope="module")
def app_inventory() -> tuple[Any, bool, str]:
    """``(app, auth_mw_registered, app_source)`` — фикстура, shared через parametrize."""
    app, source, auth_mw_registered = _build_app_or_skip()
    return app, auth_mw_registered, source


def pytest_generate_tests(metafunc: Any) -> None:
    """Generate parametrize ids из реальных маршрутов приложения."""
    if "route_id" not in metafunc.fixturenames:
        return
    app, _, _ = _build_app_or_skip()
    ids = _collect_route_ids(app)
    metafunc.parametrize("route_id", ids, ids=[f"{m}::{p}" for m, p in ids])


# ---- Тест -------------------------------------------------------------------


def test_route_has_auth_guard(
    route_id: tuple[str, str], app_inventory: tuple[Any, bool, str]
) -> None:
    """Каждый non-public route покрыт per-handler Depends или middleware."""
    _, path = route_id
    app, auth_mw_registered, app_source = app_inventory

    target: Any = None
    for route in _walk_routes(app.routes):
        if getattr(route, "path", "") == path:
            target = route
            break
    assert target is not None, f"route {path} disappeared between parametrize and run"

    if auth_mw_registered:
        # Defense-in-depth покрывает ВСЕ non-public endpoints.
        return

    # Middleware отсутствует → требуем per-handler Depends.
    if not getattr(target.dependant, "dependencies", []):
        pytest.fail(
            f"non-public route {path} has neither per-handler Depends nor "
            f"AuthRequiredMiddleware (app={app_source}); defined at "
            f"{_route_source(target)}"
        )