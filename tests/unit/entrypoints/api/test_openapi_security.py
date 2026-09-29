"""Тесты аннотации OpenAPI схемами аутентификации.

Контекст дефекта: аутентификация обеспечивается pure-ASGI middleware
(:mod:`auth_required`), который FastAPI не выводит в схему. Спецификация
публиковалась с пустым ``components.securitySchemes`` и без поля ``security``
на всех операциях, при том что запросы без credentials получают 401.

Проверяется главное свойство: **спецификация совпадает с реально
enforce'имым контрактом**, а не то, что схема «какая-то есть».
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI

from src.backend.entrypoints.api.openapi_security import (
    SECURITY_SCHEMES,
    annotate_openapi,
    apply_security_to_openapi,
)
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    is_path_public,
)

_HTTP_METHODS = ("get", "post", "put", "delete", "patch")


def _schema_with(paths: dict[str, list[str]]) -> dict[str, Any]:
    """Минимальная OpenAPI-схема: path → список HTTP-методов."""
    return {
        "openapi": "3.1.0",
        "paths": {
            p: {m: {"responses": {}} for m in methods} for p, methods in paths.items()
        },
    }


@pytest.mark.unit
class TestSecuritySchemesDeclared:
    """Схемы аутентификации объявлены в components."""

    def test_all_schemes_present(self) -> None:
        """Каждая credential-схема попадает в components.securitySchemes."""
        schema = annotate_openapi(_schema_with({"/api/v1/x": ["get"]}))
        schemes = schema["components"]["securitySchemes"]
        assert set(schemes) == set(SECURITY_SCHEMES)
        assert schemes["bearerAuth"]["scheme"] == "bearer"
        assert schemes["apiKeyAuth"]["name"] == "X-API-Key"
        assert schemes["apiKeyAuth"]["in"] == "header"
        assert schemes["basicAuth"]["scheme"] == "basic"
        assert schemes["samlSession"]["in"] == "cookie"

    def test_scheme_names_match_security_references(self) -> None:
        """Каждая ссылка в security разрешается в объявленную схему."""
        schema = annotate_openapi(_schema_with({"/api/v1/x": ["get"]}))
        declared = set(schema["components"]["securitySchemes"])
        required = schema["paths"]["/api/v1/x"]["get"]["security"]
        assert required
        for alternative in required:
            assert set(alternative) <= declared


@pytest.mark.unit
class TestOperationSecurityMatchesRuntimeGuard:
    """Признак public берётся из того же источника, что и рантайм-guard."""

    def test_non_public_operation_requires_auth(self) -> None:
        """Непубличная операция получает требования аутентификации."""
        schema = annotate_openapi(_schema_with({"/api/v1/user/all/": ["get"]}))
        security = schema["paths"]["/api/v1/user/all/"]["get"]["security"]
        assert security == [{name: []} for name in SECURITY_SCHEMES]

    @pytest.mark.parametrize("prefix", ["/health", "/ready", "/docs", "/metrics"])
    def test_public_prefixes_are_marked_public(self, prefix: str) -> None:
        """Публичные префиксы получают пустой security (= аутентификация не нужна)."""
        schema = annotate_openapi(_schema_with({prefix: ["get"]}))
        assert schema["paths"][prefix]["get"]["security"] == []

    def test_auth_endpoints_follow_the_auth_required_layer_only(self) -> None:
        """Login/step-up помечены public — и это верно для AuthRequiredMiddleware.

        Эти пути закрывает **следующий** слой, ``LoginStepUpMiddleware``
        (``X-Step-Up-Token`` + rate-limit 10/5min), а не auth-guard. OpenAPI
        не умеет описывать такой guard, поэтому поле ``security`` отражает
        ровно тот слой, который здесь аннотируется. Тест фиксирует это
        расхождение намеренно, чтобы его не «починили» случайно, не сверив
        слои между собой.
        """
        for path in ("/api/v1/auth/login", "/api/v1/auth/step-up-request"):
            assert is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES)
            schema = annotate_openapi(_schema_with({path: ["post"]}))
            assert schema["paths"][path]["post"]["security"] == []

    def test_annotation_agrees_with_guard_for_every_public_prefix(self) -> None:
        """Схема и guard дают одинаковый вердикт по всем каноническим префиксам."""
        for prefix in DEFAULT_PUBLIC_PATH_PREFIXES:
            schema = annotate_openapi(_schema_with({prefix: ["get"]}))
            annotated_public = schema["paths"][prefix]["get"]["security"] == []
            guard_public = is_path_public(prefix, DEFAULT_PUBLIC_PATH_PREFIXES)
            assert annotated_public == guard_public, prefix

    def test_all_methods_of_one_path_get_same_requirement(self) -> None:
        """GET и POST одного пути не могут различаться по public-статусу."""
        schema = annotate_openapi(
            _schema_with({"/api/v1/user/all/": ["get", "post", "delete"]})
        )
        requirements = [
            schema["paths"]["/api/v1/user/all/"][m]["security"]
            for m in ("get", "post", "delete")
        ]
        assert requirements[0] == requirements[1] == requirements[2]
        assert requirements[0] != []


@pytest.mark.unit
class TestApplyToApp:
    """Подключение к приложению через app.openapi."""

    def test_openapi_endpoint_returns_annotated_schema(self) -> None:
        """FastAPI-приложение после подключения отдаёт аннотированную схему."""
        app = FastAPI()

        @app.get("/api/v1/thing")
        async def thing() -> dict[str, bool]:
            return {"ok": True}

        @app.get("/health")
        async def health() -> dict[str, str]:
            return {"status": "alive"}

        apply_security_to_openapi(app)
        schema = app.openapi()

        assert schema["components"]["securitySchemes"]
        assert schema["paths"]["/api/v1/thing"]["get"]["security"] != []
        assert schema["paths"]["/health"]["get"]["security"] == []

    def test_repeated_calls_are_stable(self) -> None:
        """Повторный вызов не размножает схемы и не ломает схему."""
        app = FastAPI()

        @app.get("/api/v1/thing")
        async def thing() -> dict[str, bool]:
            return {"ok": True}

        apply_security_to_openapi(app)
        first = app.openapi()
        second = app.openapi()
        assert set(second["components"]["securitySchemes"]) == set(SECURITY_SCHEMES)
        assert (
            first["paths"]["/api/v1/thing"]["get"]["security"]
            == (second["paths"]["/api/v1/thing"]["get"]["security"])
        )

    def test_non_http_keys_are_ignored(self) -> None:
        """Ключи path-item, не являющиеся операциями, не получают security."""
        schema = annotate_openapi(
            {
                "paths": {
                    "/api/v1/thing": {
                        "parameters": [{"name": "x", "in": "query"}],
                        "summary": "not an operation",
                        "get": {"responses": {}},
                    }
                }
            }
        )
        item = schema["paths"]["/api/v1/thing"]
        assert "security" not in item["parameters"]
        assert "security" not in item["summary"]
        assert item["get"]["security"] != []

    def test_annotation_failure_does_not_break_openapi(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Сбой аннотации не превращается в 500 /docs — возвращается исходная схема.

        Спецификация — документация, а не контроль доступа: падение
        аннотации не должно поднимать приложение.
        """
        app = FastAPI()

        @app.get("/api/v1/thing")
        async def thing() -> dict[str, bool]:
            return {"ok": True}

        apply_security_to_openapi(app)

        def _boom(_schema: dict[str, Any]) -> dict[str, Any]:
            raise TypeError("simulated annotation failure")

        monkeypatch.setattr(
            "src.backend.entrypoints.api.openapi_security.annotate_openapi", _boom
        )
        schema = app.openapi()
        assert schema["paths"]["/api/v1/thing"]["get"]  # исходная схема цела


@pytest.mark.unit
class TestDescriptionsSurviveResponseMasking:
    """Описания схем не должны искажаться маскированием ответов.

    Найдено на живом сервисе: ``pii_masker`` считает фамилией любое русское
    прилагательное на -ский/-ова/-ин (``Статический`` → ``***``) и портит
    описание в уже опубликованной спецификации. Сужать тот паттерн нельзя без
    ослабления privacy-контура, поэтому тексты подобраны так, чтобы не
    попадать под ложное срабатывание. Тест не даёт вернуть это молча.
    """

    def test_survives_data_masking_middleware(self) -> None:
        """``DataMaskingMiddleware`` не трогает описания схем."""
        from src.backend.entrypoints.middlewares.data_masking import (
            DataMaskingMiddleware,
        )

        middleware = DataMaskingMiddleware(lambda *a, **k: None)  # type: ignore[arg-type]
        for name, scheme in SECURITY_SCHEMES.items():
            description = scheme.get("description")
            if description is None:
                continue
            assert middleware._mask_value(description) == description, name

    def test_survives_pii_masker(self) -> None:
        """``core.security.pii_masker`` не трогает описания схем."""
        from src.backend.core.security.pii_masker import default_masker

        masker = default_masker()
        for name, scheme in SECURITY_SCHEMES.items():
            description = scheme.get("description")
            if description is None:
                continue
            assert masker.mask_text(description) == description, name
