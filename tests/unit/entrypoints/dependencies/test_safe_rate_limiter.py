"""Tests для SafeRateLimiter (fix для _IncludedRouter.path bug, 2026-10-15).

Audit re-audit (2026-10-15) обнаружил pre-existing bug в
``fastapi_limiter==0.2.0`` upstream ``RateLimiter.__call__``: при обходе
``request.app.routes`` для вложенных роутеров (``_IncludedRouter``)
отсутствует атрибут ``.path``, что приводит к ``AttributeError`` → 500
internal error на ``/api/v1/invocations``.

:class:`SafeRateLimiter` — минимально-совместимый subclass, который
использует ``getattr(route, 'path', ...)`` / ``getattr(route, 'prefix', ...)``
и обрабатывает роуты без HTTP methods (lifespan, mounts).

Тесты проверяют:

1. ``SafeRateLimiter`` существует и subclass upstream;
2. APIRoute с ``.path`` работает (positive path);
3. ``_IncludedRouter`` с ``.prefix`` не роняет AttributeError;
4. Route без methods (lifespan) пропускается без падения;
5. ``_skip_limiter`` attribute на endpoint'е → return без acquire;
6. ``_UpstreamRateLimiter.__call__`` для сравнения — действительно падает
   на _IncludedRouter (regression protection).
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# ─────────────────────────── fixtures ───────────────────────────


class _FakeIncludedRouter:
    """Эмуляция _IncludedRouter (sub-router из FastAPI).

    У _IncludedRouter ЕСТЬ .routes, ЕСТЬ .prefix, НЕТ .path.
    """

    def __init__(self, prefix: str, routes: list[Any] | None = None) -> None:
        self.prefix = prefix
        self.routes = routes or []


class _FakeAPIRoute:
    """Эмуляция APIRoute (leaf-route)."""

    def __init__(
        self,
        path: str,
        methods: set[str],
        dependencies: list[Any] | None = None,
        endpoint: Any | None = None,
    ) -> None:
        self.path = path
        self.methods = methods
        self.dependencies = dependencies or []
        self.endpoint = endpoint


@pytest.fixture
def captured_acquire() -> dict[str, Any]:
    """Захватывает аргументы try_acquire_async для верификации rate-key."""
    return {}


@pytest.fixture
def fake_limiter(captured_acquire: dict[str, Any]) -> MagicMock:
    """Fake limiter с try_acquire_async, который всегда True.

    Принимает любые kwargs (включая ``blocking=`` который upstream
    RateLimiter передаёт явно) — это compat-адаптер для тестов.
    """
    limiter = MagicMock()

    async def _try_acquire(*args: Any, **kwargs: Any) -> bool:
        # Upstream вызывает try_acquire_async(key, blocking=self.blocking)
        key = args[0] if args else kwargs.get("key", "pyrate")
        captured_acquire["key"] = key
        captured_acquire["kwargs"] = kwargs
        return True

    limiter.try_acquire_async = _try_acquire
    return limiter


# ─────────────────────────── tests ───────────────────────────


class TestSafeRateLimiter:
    """Regression-protection для _IncludedRouter.path bug."""

    def test_safe_rate_limiter_is_subclass_of_upstream(self) -> None:
        """``SafeRateLimiter`` должен быть subclass upstream ``RateLimiter``."""
        from fastapi_limiter.depends import RateLimiter

        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        assert issubclass(SafeRateLimiter, RateLimiter), (
            "SafeRateLimiter must subclass upstream RateLimiter; "
            "иначе Depends registration ломается"
        )

    @pytest.mark.asyncio
    async def test_api_route_with_path_works(
        self, fake_limiter: MagicMock, captured_acquire: dict[str, Any]
    ) -> None:
        """APIRoute (leaf-route) с .path: SafeRateLimiter находит совпадение
        и acquire'ит permit (rate-key непустой)."""
        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        route = _FakeAPIRoute(path="/api/v1/invocations", methods={"POST"})
        request = MagicMock()
        request.app.routes = [route]
        request.scope = {"path": "/api/v1/invocations", "method": "POST"}
        request.method = "POST"

        # identifier callback
        async def _ident(_r: Any) -> str:
            return "user-1"

        limiter_obj = SafeRateLimiter(
            limiter=fake_limiter,
            identifier=_ident,
            callback=AsyncMock(),
            blocking=False,
        )
        response = SimpleNamespace()
        await limiter_obj(request, response)
        # rate-key содержит route_index=0
        assert captured_acquire.get("key") == "user-1:0:0", (
            f"Expected rate key 'user-1:0:0', got {captured_acquire.get('key')!r}; "
            "route index resolution broken"
        )

    @pytest.mark.asyncio
    async def test_included_router_with_prefix_does_not_crash(
        self, fake_limiter: MagicMock, captured_acquire: dict[str, Any]
    ) -> None:
        """_IncludedRouter (sub-router) с .prefix: SafeRateLimiter НЕ падает
        на AttributeError, продолжает итерацию, находит leaf APIRoute
        внутри, acquire'ит permit.
        """
        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        leaf = _FakeAPIRoute(path="/api/v1/invocations", methods={"POST"})
        sub = _FakeIncludedRouter(prefix="/api/v1/invocations", routes=[leaf])
        request = MagicMock()
        # app.routes: сначала sub-router, потом leaf
        request.app.routes = [sub, leaf]
        request.scope = {"path": "/api/v1/invocations", "method": "POST"}
        request.method = "POST"

        async def _ident(_r: Any) -> str:
            return "user-2"

        limiter_obj = SafeRateLimiter(
            limiter=fake_limiter,
            identifier=_ident,
            callback=AsyncMock(),
            blocking=False,
        )
        response = SimpleNamespace()
        # ДОЛЖНО работать без AttributeError. Upstream RateLimiter
        # упал бы на первом route (sub) с .path.
        await limiter_obj(request, response)
        # rate-key acquired (хотя бы один permit)
        assert "key" in captured_acquire, (
            "SafeRateLimiter не acquire'нул permit на included router; "
            f"captured: {captured_acquire}"
        )

    @pytest.mark.asyncio
    async def test_route_without_methods_is_skipped(
        self, fake_limiter: MagicMock, captured_acquire: dict[str, Any]
    ) -> None:
        """Route без ``methods`` (lifespan / mount) пропускается без падения.

        Upstream падал бы с ``TypeError: 'NoneType' is not iterable``
        на строке ``request.method in route.methods`` — мы через
        ``getattr(route, 'methods', None)`` обрабатываем.
        """
        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        no_methods_route = SimpleNamespace(
            path="/some/lifespan"
            # no .methods at all
        )
        real_route = _FakeAPIRoute(path="/api/v1/health", methods={"GET"})
        request = MagicMock()
        request.app.routes = [no_methods_route, real_route]
        request.scope = {"path": "/api/v1/health", "method": "GET"}
        request.method = "GET"

        async def _ident(_r: Any) -> str:
            return "user-3"

        limiter_obj = SafeRateLimiter(
            limiter=fake_limiter,
            identifier=_ident,
            callback=AsyncMock(),
            blocking=False,
        )
        response = SimpleNamespace()
        await limiter_obj(request, response)
        # rate-key acquired (real_route matched, no_methods_route skipped)
        assert "key" in captured_acquire, (
            f"SafeRateLimiter не обработал real_route: {captured_acquire}"
        )

    @pytest.mark.asyncio
    async def test_skip_limiter_attribute_returns_immediately(
        self, fake_limiter: MagicMock, captured_acquire: dict[str, Any]
    ) -> None:
        """Endpoint с ``_skip_limiter=True`` → return без acquire."""
        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        def _endpoint() -> None:
            pass

        _endpoint._skip_limiter = True  # type: ignore[attr-defined]
        route = _FakeAPIRoute(path="/health", methods={"GET"}, endpoint=_endpoint)
        request = MagicMock()
        request.app.routes = [route]
        request.scope = {"path": "/health", "method": "GET"}
        request.method = "GET"

        async def _ident(_r: Any) -> str:
            return "user-4"

        limiter_obj = SafeRateLimiter(
            limiter=fake_limiter,
            identifier=_ident,
            callback=AsyncMock(),
            blocking=False,
        )
        response = SimpleNamespace()
        await limiter_obj(request, response)
        # permit NOT acquired
        assert "key" not in captured_acquire, (
            f"_skip_limiter endpoint должен skip acquire, но acquired: {captured_acquire}"
        )

    @pytest.mark.asyncio
    async def test_upstream_rate_limiter_crashes_on_included_router(
        self, fake_limiter: MagicMock
    ) -> None:
        """Upstream ``RateLimiter`` действительно падает на _IncludedRouter.

        Это regression-protection тест: если upstream когда-нибудь
        починит — наш SafeRateLimiter можно будет убрать. Пока upstream
        сломан, мы обязаны его sub-class'ить.
        """
        from fastapi_limiter.depends import RateLimiter

        sub = _FakeIncludedRouter(prefix="/api/v1")
        leaf = _FakeAPIRoute(path="/api/v1/invocations", methods={"POST"})
        request = MagicMock()
        request.app.routes = [sub, leaf]
        request.scope = {"path": "/api/v1/invocations", "method": "POST"}
        request.method = "POST"

        async def _ident(_r: Any) -> str:
            return "user"

        upstream = RateLimiter(
            limiter=fake_limiter,
            identifier=_ident,
            callback=AsyncMock(),
            blocking=False,
        )
        response = SimpleNamespace()
        with pytest.raises(AttributeError) as exc_info:
            await upstream(request, response)
        # Подтверждаем что ошибка именно в строке 'route.path' (upstream bug)
        assert "path" in str(exc_info.value).lower() or "'path'" in str(
            exc_info.value
        ), f"Upstream должен падать с AttributeError на .path; got: {exc_info.value!r}"

    @pytest.mark.asyncio
    async def test_get_default_rate_limiter_returns_safe_subclass(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``get_default_rate_limiter()`` возвращает ``SafeRateLimiter`` instance.

        Это гарантирует, что ``Depends(get_default_rate_limiter())`` в
        production даёт SafeRateLimiter (а не upstream), и pre-existing
        bug не возвращается через кеш lru_cache.
        """
        # Сбросить lru_cache — singleton может остаться от других тестов
        from src.backend.entrypoints.dependencies import rate_limit

        rate_limit.get_default_rate_limiter.cache_clear()
        rate_limit.get_default_limiter.cache_clear()

        # Подменяем secure_settings чтобы RedisLimiterAdapter не пытался
        # реально подключиться к Redis
        from src.backend.core.config.security import secure_settings

        monkeypatch.setattr(secure_settings, "rate_limit", 100, raising=False)
        monkeypatch.setattr(
            secure_settings, "rate_time_measure_seconds", 60, raising=False
        )

        limiter = rate_limit.get_default_rate_limiter()
        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        assert isinstance(limiter, SafeRateLimiter), (
            f"get_default_rate_limiter() должен возвращать SafeRateLimiter; "
            f"got {type(limiter).__name__}"
        )
        # Очищаем cache для следующих тестов
        rate_limit.get_default_rate_limiter.cache_clear()
        rate_limit.get_default_limiter.cache_clear()


class TestSafeRateLimiterOpenAPI:
    """Regression 2026-10-15: зависимость не должна ломать HTTP-контракт.

    ``SafeRateLimiter.__call__`` — override с аннотациями ``Any`` вместо
    starlette ``Request``/``Response``. FastAPI не распознаёт ``Any`` как
    special-типы и объявляет оба параметра как **required query params**.
    В следствие этого OpenAPI для ``POST /api/v1/invocations`` публикует
    фиктивные ``?request=&response=``, и реальный HTTP-вызов падает с 422
    ещё до попадания в handler.
    """

    def test_call_annotations_are_special_request_response(self) -> None:
        """``__call__`` аннотирован настоящими Request/Response, не Any."""
        import inspect

        from starlette.requests import Request as StarletteRequest
        from starlette.responses import Response as StarletteResponse

        from src.backend.entrypoints.dependencies.rate_limit import SafeRateLimiter

        hints = inspect.get_annotations(SafeRateLimiter.__call__, eval_str=True)
        assert hints["request"] is StarletteRequest, (
            f"request должен быть starlette Request, получено {hints['request']}"
        )
        assert hints["response"] is StarletteResponse, (
            f"response должен быть starlette Response, получено {hints['response']}"
        )

    def test_dependency_does_not_add_query_params_to_openapi(self) -> None:
        """Depends(SafeRateLimiter) не добавляет параметров в схему."""
        from fastapi import Depends, FastAPI
        from fastapi.testclient import TestClient

        from src.backend.entrypoints.dependencies.rate_limit import (
            get_default_rate_limiter,
        )

        app = FastAPI()
        limiter = get_default_rate_limiter()
        limiter.limiter = MagicMock()  # type: ignore[assignment]
        limiter.limiter.try_acquire_async = AsyncMock(return_value=True)

        async def _ident(_r: Any) -> str:
            return "user"

        limiter.identifier = _ident

        @app.post("/probe")
        async def _probe(
            payload: dict[str, Any], _rl: None = Depends(limiter)
        ) -> dict[str, Any]:
            return payload

        schema = app.openapi()["paths"]["/probe"]["post"]
        names = {p["name"] for p in schema.get("parameters", [])}
        assert names == set(), f"Неожиданные query-параметры в контракте: {names}"

        client = TestClient(app)
        resp = client.post("/probe", json={"hello": "world"})
        assert resp.status_code == 200, resp.text
        assert resp.json() == {"hello": "world"}


class TestRedisLimiterAdapterProtocolCompat:
    """Regression 2026-10-15: adapter обязан совпадать с pyrate_limiter.

    ``RateLimiter.__call__`` (upstream и наш :class:`SafeRateLimiter`) вызывает
    ``limiter.try_acquire_async(key, blocking=self.blocking)``.
    ``RedisLimiterAdapter.try_acquire_async`` не принимал ``blocking`` →
    ``TypeError`` → 500 ``internal_error`` на каждом rate-limited endpoint.
    Существующие тесты мокали ``try_acquire_async`` целиком и не ловили
    несовместимость сигнатур.
    """

    def test_signature_matches_pyrate_limiter(self) -> None:
        """Все kwargs из pyrate_limiter.Limiter.try_acquire_async приняты."""
        import inspect

        from pyrate_limiter import Limiter

        from src.backend.entrypoints.dependencies.rate_limit import RedisLimiterAdapter

        upstream = set(inspect.signature(Limiter.try_acquire_async).parameters)
        ours = set(inspect.signature(RedisLimiterAdapter.try_acquire_async).parameters)
        missing = upstream - ours
        assert not missing, (
            f"RedisLimiterAdapter не принимает kwargs из pyrate_limiter: {missing}"
        )

    @pytest.mark.asyncio
    async def test_accepts_blocking_keyword(self) -> None:
        """Реальный вызов с blocking= не падает (без мока на сигнатуре)."""
        from src.backend.entrypoints.dependencies.rate_limit import RedisLimiterAdapter

        adapter = RedisLimiterAdapter(rate_limit=5, window_seconds=60)
        limiter = MagicMock()
        limiter.check = AsyncMock(return_value=None)
        object.__setattr__(adapter, "_limiter", limiter)

        assert await adapter.try_acquire_async("k", blocking=False) is True
        assert await adapter.try_acquire_async("k", blocking=True) is True
        assert await adapter.try_acquire_async("k") is True
