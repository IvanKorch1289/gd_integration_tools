"""Регресс-тесты: OpenAPI-контракт совпадает с auth-guard и стабилен.

Контекст дефекта
----------------
``apply_security_to_openapi`` вызывал аннотации в порядке
``annotate_openapi → annotate_completeness → annotate_error_responses``.
``annotate_completeness`` публикует 16 скрытых legacy-алиасов
(``/api/v1/orders/*``, ``/api/v1/users/*``, ``/api/v1/files/*``,
``/api/v1/orderkinds/*``) — и делал это **после** security-аннотации.

Последствия (подтверждены на живом приложении):

* 16 legacy-операций оставались без поля ``security`` → спецификация
  объявляла их публичными, тогда как ``AuthRequiredMiddleware`` отдаёт
  по ним 401;
* FastAPI кеширует схему в ``app.openapi_schema``, поэтому на втором
  запросе security-аннотация уже видела легаси и дописывала ``security``.
  Опубликованный документ менялся между первым и вторым ответом
  (``/openapi.json``: ETag «ce9ffc4c9828339d» → «9401b496a404767d»),
  то есть клиенты получали два разных контракта API.

Проверяется: (1) у каждой операции есть ``security``, (2) опубликованная
схема байт-в-байт стабильна между вызовами.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI

from src.backend.entrypoints.api.generator.legacy_aliases import register_legacy_aliases
from src.backend.entrypoints.api.openapi_security import (
    SECURITY_SCHEMES,
    apply_security_to_openapi,
)

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")


def _app_with_legacy_aliases() -> FastAPI:
    """Минимальное приложение со скрытыми legacy-алиасами."""
    app = FastAPI()
    register_legacy_aliases(app)
    apply_security_to_openapi(app)
    return app


def _snapshot(schema: dict[str, Any]) -> str:
    """Сериализованный вид схемы (порядок ключей тоже значим)."""
    return json.dumps(schema, ensure_ascii=False)


@pytest.mark.unit
class TestLegacyAliasesDeclareSecurity:
    """Legacy-алиасы описаны как защищённые (как их и защищает guard)."""

    def test_legacy_operations_have_security(self) -> None:
        """Каждая опубликованная legacy-операция имеет непустой ``security``."""
        schema = _app_with_legacy_aliases().openapi()

        operation = schema["paths"]["/api/v1/orders/all/"]["get"]
        assert operation["security"], "legacy-операция опубликована как публичная"
        assert operation["security"] == [{name: []} for name in SECURITY_SCHEMES]

    def test_every_operation_declares_security(self) -> None:
        """Ни одна операция схемы не осталась без ``security``."""
        schema = _app_with_legacy_aliases().openapi()

        without_security = [
            (method, path)
            for path, path_item in schema["paths"].items()
            for method, operation in path_item.items()
            if method.lower() in _HTTP_METHODS and "security" not in operation
        ]
        assert not without_security, without_security


@pytest.mark.unit
class TestPublishedSchemaIsStable:
    """Опубликованная схема не меняется между запросами."""

    def test_second_call_matches_first(self) -> None:
        """Первый и второй ответ ``/openapi.json`` идентичны."""
        app = _app_with_legacy_aliases()

        first = _snapshot(app.openapi())
        second = _snapshot(app.openapi())
        third = _snapshot(app.openapi())

        assert first == second
        assert second == third

    def test_legacy_security_present_on_first_call(self) -> None:
        """Уже первый ответ содержит ``security`` у legacy-операций."""
        schema = _app_with_legacy_aliases().openapi()

        assert schema["paths"]["/api/v1/orders/create/"]["post"]["security"]
