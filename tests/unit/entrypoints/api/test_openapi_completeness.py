"""ADR-0423 — полнота OpenAPI: ``requestBody``, 4xx и скрытые legacy-маршруты.

Контекст дефекта
----------------
Аудит кластера F6b-2 зафиксировал три пробела опубликованной спецификации:

* **188 мутаций без ``requestBody``.** FastAPI выводит ``requestBody`` только
  для параметров тела в сигнатуре обработчика; обработчики, читающие тело
  вручную (``await request.json()``, raw-поток, ``await request.form()``), тела
  в схеме не имели — хотя принимали его в рантайме.
* **16 legacy-алиасов** (``/api/v1/orders/*``, ``/api/v1/users/*``,
  ``/api/v1/files/*``, ``/api/v1/orderkinds/*``) зарегистрированы с
  ``include_in_schema=False``: маршруты живые, но схема о них молчала, а
  Streamlit на них опирается.
* **Реальные 4xx без описания:** 413/415 (лимиты загрузки файлов) и
  401/429 (``LoginStepUpMiddleware`` — step-up-токен и rate-limit).

Что проверяется
---------------
* мутация, принимающая тело, описывает ``requestBody``;
* каждая мутация без ``requestBody`` имеет **документированную причину**
  (гейт: недокументированных исключений быть не должно);
* скрытые legacy-маршруты опубликованы как ``deprecated``-операции;
* реальные 4xx присутствуют в схеме.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI, Request

from src.backend.entrypoints.api.generator.legacy_aliases import register_legacy_aliases
from src.backend.entrypoints.api.openapi_completeness import (
    AUTO_ACTION_PREFIX,
    annotate_completeness,
    classify_missing_request_body,
    undocumented_mutations_without_request_body,
)
from src.backend.entrypoints.api.openapi_security import apply_security_to_openapi

_MUTATIONS = ("post", "put", "patch", "delete")


@pytest.fixture(scope="module")
def app_schema() -> dict[str, Any]:
    """Схема живого приложения (все роуты + авто-регистрация + алиасы)."""
    from src.backend.plugins.composition.app_factory import create_app

    return create_app().openapi()


def _operations(schema: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Собрать ``(method, path, operation)`` по всем операциям схемы."""
    result: list[tuple[str, str, dict[str, Any]]] = []
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() in _MUTATIONS and isinstance(operation, dict):
                result.append((method.lower(), path, operation))
    return result


@pytest.mark.unit
class TestRequestBodyContract:
    """Мутация, принимающая тело, описывает ``requestBody``."""

    def test_auto_action_mutation_has_request_body(self) -> None:
        """Auto-registered action (``await request.json()``) описывает тело."""
        app = FastAPI()

        @app.post("/api/v1/auto/demo.action")
        async def demo(request: Request) -> dict[str, bool]:
            """Заглушка auto-action."""
            return {"ok": True}

        apply_security_to_openapi(app)
        operation = app.openapi()["paths"]["/api/v1/auto/demo.action"]["post"]

        assert "requestBody" in operation
        content = operation["requestBody"]["content"]
        assert "application/json" in content

    def test_upload_stream_body_is_binary(self) -> None:
        """Streaming-загрузка описывает бинарное тело, а не JSON."""
        app = FastAPI()

        @app.post("/api/v1/storage/upload-stream")
        async def upload_stream(request: Request) -> dict[str, bool]:
            """Заглушка streaming-загрузки."""
            return {"ok": True}

        apply_security_to_openapi(app)
        operation = app.openapi()["paths"]["/api/v1/storage/upload-stream"]["post"]

        content = operation["requestBody"]["content"]
        assert "application/octet-stream" in content
        assert content["application/octet-stream"]["schema"]["format"] == "binary"

    def test_native_request_body_is_preserved(self) -> None:
        """Объявленное в сигнатуре тело не переписывается аннотацией."""
        app = FastAPI()

        @app.post("/api/v1/items")
        async def create_item(payload: dict[str, Any]) -> dict[str, bool]:
            """Эндпоинт с объявленным телом."""
            return {"ok": True}

        apply_security_to_openapi(app)
        operation = app.openapi()["paths"]["/api/v1/items"]["post"]

        assert (
            operation["requestBody"]["content"]["application/json"]["schema"]["type"]
            == "object"
        )


@pytest.mark.unit
class TestDocumentedExceptions:
    """Каждая мутация без ``requestBody`` имеет документированную причину."""

    def test_no_undocumented_mutations_without_request_body(
        self, app_schema: dict[str, Any]
    ) -> None:
        """Гейт: ни одна мутация без тела не осталась без объяснения."""
        undocumented = undocumented_mutations_without_request_body(app_schema)
        assert not undocumented, (
            f"мутации без requestBody и без документированной причины: {undocumented}"
        )

    def test_every_mutation_has_4xx_response(self, app_schema: dict[str, Any]) -> None:
        """Каждая мутация описывает хотя бы один 4xx-ответ."""
        offenders: list[str] = []
        for method, path, operation in _operations(app_schema):
            codes = set(operation.get("responses", {}))
            if not any(code.startswith("4") for code in codes):
                offenders.append(f"{method.upper()} {path} → {sorted(codes)}")
        assert not offenders, f"мутации без 4xx-ответов: {offenders}"

    def test_classification_is_stable(self, app_schema: dict[str, Any]) -> None:
        """Причина исключения непустая и воспроизводимая."""
        for method, path, operation in _operations(app_schema):
            if "requestBody" in operation:
                continue
            reason = classify_missing_request_body(operation, method, path)
            assert reason, f"{method.upper()} {path} — нет причины"


@pytest.mark.unit
class TestOperationErrors:
    """Реальные 4xx-ответы описаны в схеме."""

    def test_upload_endpoints_document_413_and_415(
        self, app_schema: dict[str, Any]
    ) -> None:
        """Лимиты загрузки отражены в схеме."""
        for path in ("/api/v1/storage/upload_file", "/api/v1/storage/upload-stream"):
            responses = app_schema["paths"][path]["post"]["responses"]
            assert {"413", "415"} <= set(responses), path

    def test_login_documents_step_up_and_rate_limit(
        self, app_schema: dict[str, Any]
    ) -> None:
        """Login: 401 (step-up-токен) и 429 (rate-limit)."""
        responses = app_schema["paths"]["/api/v1/auth/login"]["post"]["responses"]
        assert {"401", "429"} <= set(responses)

    def test_step_up_request_documents_rate_limit(
        self, app_schema: dict[str, Any]
    ) -> None:
        """Public-мутация step-up-request описывает 429."""
        responses = app_schema["paths"]["/api/v1/auth/step-up-request"]["post"][
            "responses"
        ]
        assert "429" in set(responses)


@pytest.mark.unit
class TestLegacyAliasesPublished:
    """Скрытые legacy-маршруты опубликованы как ``deprecated``."""

    def _legacy_app_schema(self) -> dict[str, Any]:
        app = FastAPI()
        register_legacy_aliases(app)
        apply_security_to_openapi(app)
        return app.openapi()

    def test_legacy_alias_is_visible_and_deprecated(self) -> None:
        """Legacy-алиас виден в схеме и помечен deprecated."""
        schema = self._legacy_app_schema()
        operation = schema["paths"]["/api/v1/orders/all/"]["get"]
        assert operation["deprecated"] is True
        assert operation["x-legacy-alias"] is True

    def test_legacy_mutation_has_request_body(self) -> None:
        """Legacy-алиас читает JSON-тело вручную — тело описано."""
        schema = self._legacy_app_schema()
        operation = schema["paths"]["/api/v1/orders/create/"]["post"]
        assert "application/json" in operation["requestBody"]["content"]

    def test_infrastructure_aliases_stay_hidden(self) -> None:
        """Инфраструктурные алиасы (``/healthz``, ``/livez``) не публикуются."""
        schema = self._legacy_app_schema()
        for path in ("/healthz", "/livez", "/metrics"):
            assert path not in schema["paths"], path


@pytest.mark.unit
class TestAutoPrefixConsistency:
    """Префикс auto-action'ов не разъезжается с регистратором."""

    def test_auto_prefix_matches_registrar(self) -> None:
        """Константа префикса совпадает с ``auto_register._AUTO_PREFIX``."""
        from src.backend.entrypoints.api.generator import auto_register

        assert AUTO_ACTION_PREFIX.rstrip("/") == auto_register._AUTO_PREFIX


@pytest.mark.unit
class TestAnnotateCompletenessDirect:
    """Прямой вызов аннотации полноты (без обёртки FastAPI)."""

    def test_annotate_completeness_is_idempotent(self) -> None:
        """Повторный вызов не ломает и не дублирует схему."""
        app = FastAPI()

        @app.post("/api/v1/auto/demo.action")
        async def demo(request: Request) -> dict[str, bool]:
            """Заглушка auto-action."""
            return {"ok": True}

        register_legacy_aliases(app)
        schema = app.openapi()
        first = annotate_completeness(app, schema)
        second = annotate_completeness(app, first)
        assert second["paths"]["/api/v1/auto/demo.action"]["post"]["requestBody"]
        assert (
            second["paths"]["/api/v1/orders/create/"]["post"]["requestBody"]
            == first["paths"]["/api/v1/orders/create/"]["post"]["requestBody"]
        )
