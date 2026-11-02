"""ADR-0422 — полнота OpenAPI: 4xx-ответы и requestBody.

Контекст дефекта
----------------
Аудит F6b зафиксировал: **205 из 443 операций** не описывали ни одного
4xx-ответа, хотя auth-слой отдаёт 401 (нет credentials) и 403 (не хватает
роли / CSRF-токена). Клиент, сгенерированный из спецификации, не знал,
что запрос может быть отклонён.

Также 157 мутаций не имели ``requestBody``. Проверять это «на каждый
мутирующий метод» нельзя: ``DELETE /order/delete/{id}`` и
``POST /storage/upload-stream`` (raw body) тела по контракту не имеют.
Поэтому requestBody-контракт проверяется **на мутациях, у которых есть
параметры тела**, а остальные перечисляются как документированное
исключение (см. ``mutations_without_request_body`` и ADR-0422).

Публичные пути (``DEFAULT_PUBLIC_PATH_PREFIXES``) не получают 401/403:
auth-guard их пропускает.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import APIRoute

from src.backend.entrypoints.api.openapi_security import (
    ERROR_RESPONSE_SCHEMA_NAME,
    annotate_error_responses,
    annotate_openapi,
    apply_security_to_openapi,
    mutations_without_request_body,
)
from src.backend.entrypoints.api.v1.routers import get_v1_routers
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    is_path_public,
)

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")
_MUTATIONS = ("post", "put", "patch", "delete")


def _schema() -> dict[str, Any]:
    """Реальная схема v1-роутера с аннотациями security и 4xx."""
    app = FastAPI()
    app.include_router(get_v1_routers(), prefix="/api/v1")
    return annotate_error_responses(annotate_openapi(app.openapi()))


def _iter_api_routes(router: Any, prefix: str = "") -> Any:
    """Обойти APIRoute'ы вложенных ``include_router`` (FastAPI 0.141)."""
    for route in router.routes:
        original = getattr(route, "original_router", None)
        if original is not None:
            context = getattr(route, "include_context", None)
            sub_prefix = getattr(context, "prefix", "") or ""
            yield from _iter_api_routes(original, prefix + sub_prefix)
            continue
        if isinstance(route, APIRoute):
            yield prefix + route.path_format, route


@pytest.mark.unit
class TestErrorResponses:
    """Каждая защищённая операция описывает 401 и 403."""

    def test_guarded_operations_have_4xx_responses(self) -> None:
        """Нет защищённой операции без 4xx-ответа."""
        schema = _schema()
        offenders: list[str] = []
        for path, path_item in schema.get("paths", {}).items():
            if is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES):
                continue
            for method, operation in path_item.items():
                if method.lower() not in _HTTP_METHODS or not isinstance(
                    operation, dict
                ):
                    continue
                codes = set(operation.get("responses", {}))
                if not any(code.startswith("4") for code in codes):
                    offenders.append(f"{method.upper()} {path}")
        assert not offenders, f"операции без 4xx-ответов: {offenders}"

    def test_mutations_have_401_and_403(self) -> None:
        """Мутации под auth-guard'ом описывают 401 и 403."""
        schema = _schema()
        offenders: list[str] = []
        for path, path_item in schema.get("paths", {}).items():
            if is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES):
                continue
            for method, operation in path_item.items():
                if method.lower() not in _MUTATIONS or not isinstance(operation, dict):
                    continue
                codes = set(operation.get("responses", {}))
                if not {"401", "403"} <= codes:
                    offenders.append(f"{method.upper()} {path} → {sorted(codes)}")
        assert not offenders, f"мутации без 401/403: {offenders}"

    def test_public_operations_are_not_annotated(self) -> None:
        """Публичным путям 401/403 не добавляются (auth их пропускает)."""
        schema = _schema()
        for path, path_item in schema.get("paths", {}).items():
            if not is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES):
                continue
            for method, operation in path_item.items():
                if method.lower() not in _HTTP_METHODS or not isinstance(
                    operation, dict
                ):
                    continue
                codes = set(operation.get("responses", {}))
                assert "401" not in codes, f"публичная операция {method} {path}"

    def test_error_schema_is_declared(self) -> None:
        """Ответы ссылаются на объявленный компонент схемы."""
        schema = _schema()
        schemas = schema["components"]["schemas"]
        assert ERROR_RESPONSE_SCHEMA_NAME in schemas
        props = schemas[ERROR_RESPONSE_SCHEMA_NAME]["properties"]
        assert {"code", "detail"} <= set(props)


@pytest.mark.unit
class TestRequestBodyContract:
    """requestBody: есть там, где тело предусмотрено контрактом."""

    def test_mutations_with_body_params_have_request_body(self) -> None:
        """Мутация с параметрами тела обязана описывать ``requestBody``.

        Проверка идёт по живым route'ам FastAPI (``dependant.body_params``),
        а не по самой схеме — иначе проверка была бы тавтологией.
        """
        app = FastAPI()
        app.include_router(get_v1_routers(), prefix="/api/v1")
        schema = annotate_error_responses(annotate_openapi(app.openapi()))

        offenders: list[str] = []
        checked = 0
        for path, route in _iter_api_routes(get_v1_routers()):
            methods = {m.lower() for m in (route.methods or set())}
            if not methods & set(_MUTATIONS):
                continue
            if not route.dependant.body_params:
                continue
            checked += 1
            method_key = next(
                m for m in route.methods if m.lower() in _MUTATIONS
            ).lower()
            operation = schema["paths"][f"/api/v1{path}"][method_key]
            if "requestBody" not in operation:
                offenders.append(f"{path} ({route.methods})")
        assert checked > 0, "ожидались мутации с параметрами тела"
        assert not offenders, f"мутации без requestBody: {offenders}"

    def test_mutations_without_request_body_are_enumerable(self) -> None:
        """Список исключений доступен (документируется в ADR-0422)."""
        schema = _schema()
        without = mutations_without_request_body(schema)
        assert isinstance(without, list)
        for method, path in without:
            assert method in _MUTATIONS
            assert path.startswith("/")


@pytest.mark.unit
class TestOpenapiApplication:
    """Аннотация подключается к приложению."""

    def test_apply_security_to_openapi_annotates_responses(self) -> None:
        """``apply_security_to_openapi`` добавляет и security, и 4xx."""
        app = FastAPI()

        @app.post("/api/v1/items")
        async def create_item() -> dict[str, str]:
            return {"ok": "yes"}

        apply_security_to_openapi(app)
        schema = app.openapi()

        operation = schema["paths"]["/api/v1/items"]["post"]
        assert operation["responses"]["401"]["content"]["application/json"]
        assert operation["responses"]["403"]["content"]["application/json"]
        assert operation["security"]
