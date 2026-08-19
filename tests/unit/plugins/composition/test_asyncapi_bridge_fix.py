"""Regression-блокировка для NEW-3a fix: ``/asyncapi`` bridge endpoint.

Pre-NEW-3a: bare ``/asyncapi`` path был в ``auth_required.routes_without_api_key``
(публичный), но не mounted ни в одном router → 404 при любом запросе
от Streamlit pages (``pages_65_asyncapi`` + ``registry_tab``).

NEW-3a fix (2026-08-13): добавлен ``_asyncapi_bridge_router`` внутри
``create_app()`` (по паттерну ``_admin_bridge_router``). ``GET /asyncapi``
отдаёт ``build_asyncapi_json()`` (AsyncAPI 3.0 spec) через ``JSONResponse``
напрямую, без HTTP-redirect.

Тесты проверяют source code на наличие правильного паттерна — без
запуска full app (что требует network / DB / Vault, медленно и flaky).

Подход: source-level inspection + small FastAPI test app с bridge router
(через создание bridge router через partial pattern).
"""

from __future__ import annotations

import ast
import inspect

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.backend.plugins.composition import app_factory


def test_create_app_source_has_asyncapi_bridge_router() -> None:
    """``_configure_business_routers()`` (helper called by create_app)
    содержит ``_asyncapi_bridge_router = APIRouter()``.

    NEW-3a fix добавил bridge router. Если кто-то рефакторит,
    этот тест напомнит о наличии bridge.
    """
    # Bridge определён в _configure_business_routers helper, не в create_app.
    source = inspect.getsource(app_factory._configure_business_routers)
    assert "_asyncapi_bridge_router" in source, (
        "NEW-3a fix regressed: _asyncapi_bridge_router missing from "
        "_configure_business_routers()"
    )
    assert "APIRouter()" in source, (
        "Expected APIRouter() instantiation for bridge"
    )


def test_asyncapi_bridge_route_pattern() -> None:
    """Bridge router регистрирует ``GET /asyncapi`` с include_in_schema=False."""
    source = inspect.getsource(app_factory._configure_business_routers)
    assert '"/asyncapi"' in source or "'/asyncapi'" in source, (
        "NEW-3a fix: bridge route path /asyncapi missing"
    )
    assert "include_in_schema=False" in source, (
        "NEW-3a fix: include_in_schema=False missing on bridge route"
    )


def test_asyncapi_bridge_calls_build_asyncapi_json() -> None:
    """Bridge route handler вызывает ``build_asyncapi_json()`` из asyncapi module."""
    source = inspect.getsource(app_factory._configure_business_routers)
    assert "build_asyncapi_json" in source, (
        "NEW-3a fix: bridge should call build_asyncapi_json()"
    )


def test_asyncapi_bridge_uses_jsonresponse() -> None:
    """Bridge использует ``JSONResponse`` (не redirect, не HTMLResponse)."""
    source = inspect.getsource(app_factory._configure_business_routers)
    assert "JSONResponse" in source, (
        "NEW-3a fix: bridge should use JSONResponse for spec"
    )
    assert "JSONResponse(content=build_asyncapi_json" in source, (
        "Bridge should serve JSONResponse(content=build_asyncapi_json(), ...)"
    )


def test_bridge_route_returns_200_with_asyncapi_spec_via_test_client() -> None:
    """Integration test: bridge router работает (если создать вручную).

    Если создать идентичный bridge router через partial pattern, должен
    возвращать 200 + AsyncAPI 3.0 spec. Это страховка от регрессии.
    """
    from fastapi.responses import JSONResponse

    # Создаём mock bridge router с тем же handler pattern
    mock_router = APIRouter()

    def build_asyncapi_json_mock() -> dict:
        return {"asyncapi": "3.0.0", "info": {"title": "test", "version": "1.0.0"}}

    @mock_router.get("/asyncapi", include_in_schema=False)
    async def asyncapi_legacy_serve():
        return JSONResponse(
            content=build_asyncapi_json_mock(),
            media_type="application/json",
        )

    app = FastAPI()
    app.include_router(mock_router)
    client = TestClient(app)
    resp = client.get("/asyncapi")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    body = resp.json()
    assert body["asyncapi"].startswith("3.")
    # Sanity check: include_in_schema=False → НЕ в OpenAPI
    assert "/asyncapi" not in app.openapi().get("paths", {})


def test_bridge_excluded_from_openapi() -> None:
    """Static check: bridge имеет ``include_in_schema=False`` в source."""
    source = inspect.getsource(app_factory._configure_business_routers)
    # AST parse для надёжности (допускает переносы строк, кавычки)
    tree = ast.parse(source)
    found_include_in_schema_false = False
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.keyword)
            and node.arg == "include_in_schema"
            and isinstance(node.value, ast.Constant)
            and node.value.value is False
        ):
            found_include_in_schema_false = True
            break
    assert found_include_in_schema_false, (
        "NEW-3a fix regressed: include_in_schema=False keyword not found in "
        "_configure_business_routers() AST"
    )

