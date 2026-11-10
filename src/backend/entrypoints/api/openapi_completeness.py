"""Полнота OpenAPI-схемы: ``requestBody``, реальные 4xx и скрытые legacy-маршруты.

Контекст (ADR-0423, кластер F6b-2)
---------------------------------
Аудит кластера F6b-2 нашёл, что опубликованная спецификация неполна:

* **Мутации без ``requestBody``.** FastAPI выводит ``requestBody`` только
  для параметров, объявленных в сигнатуре обработчика. Эндпоинты, читающие
  тело вручную (``await request.json()``, raw-поток, ``await request.form()``),
  тела в схеме не имеют — хотя принимают его в рантайме. В полной схеме
  приложения таких мутаций было 188.
* **16 legacy-алиасов** (``/api/v1/orders/*``, ``/api/v1/users/*``,
  ``/api/v1/files/*``, ``/api/v1/orderkinds/*``) зарегистрированы с
  ``include_in_schema=False``: маршруты живые, но в схеме их нет, а
  Streamlit на них опирается. Схема молчала о живом контракте.
* **Отдельные операции умеют отдавать 4xx, о которых схема молчит:**
  ``413``/``415`` (лимиты загрузки файлов), ``401``/``429``
  (``LoginStepUpMiddleware`` — step-up-токен и rate-limit).

Что делает модуль
-----------------
* доописывает ``requestBody`` там, где тело действительно принимается, но не
  описано;
* публикует скрытые legacy-маршруты как ``deprecated``-операции (правда
  вместо молчания);
* доописывает реальные 4xx-ответы отдельных операций;
* даёт **документированное объяснение** каждой мутации без ``requestBody``
  и список недокументированных (``undocumented_mutations_without_request_body``)
  — гейт, который не даёт числу исключений расти молча.

Модуль не выдумывает контракт: ``requestBody`` добавляется только там, где
обработчик читает тело (список — ``_RAW_BODY_ENDPOINTS``), а каждое
исключение получает причину. Новые мутации без тела, не попавшие ни в
одно правило, ломают гейт ``undocumented_mutations_without_request_body`` —
это осознанный «шум»: решение «дописать тело» или «задокументировать
исключение» должно приниматься явно.
"""

from __future__ import annotations

import re
from typing import Any

from fastapi import FastAPI
from fastapi.routing import APIRoute, iter_route_contexts

from src.backend.core.logging import get_logger

__all__ = (
    "AUTO_ACTION_PREFIX",
    "annotate_completeness",
    "annotate_legacy_aliases",
    "annotate_operation_errors",
    "annotate_path_parameters",
    "annotate_request_bodies",
    "classify_missing_request_body",
    "undocumented_mutations_without_request_body",
)

_logger = get_logger(__name__)

#: HTTP-методы, описываемые как операции OpenAPI.
_HTTP_METHODS = frozenset(
    {"get", "put", "post", "delete", "options", "head", "patch", "trace"}
)

#: Методы, меняющие состояние (для них обязателен ``requestBody``-контракт).
_MUTATION_METHODS = frozenset({"post", "put", "patch", "delete"})

#: Методы, для которых тело вообще имеет смысл (``DELETE``-с-телом — нет).
_BODY_METHODS = frozenset({"post", "put", "patch"})

#: Префикс авто-регистрируемых action-эндпоинтов.
#:
#: Дублирует ``generator/auto_register.py::_AUTO_PREFIX``; расхождение
#: ловит тест ``test_auto_prefix_matches_registrar``.
AUTO_ACTION_PREFIX = "/api/v1/auto/"

#: Префикс публичного API — только такие скрытые маршруты публикуются
#: в схеме (инфраструктурные алиасы ``/healthz``, ``/livez``, ``/metrics``
#: намеренно остаются вне контракта API).
_API_PREFIX = "/api/v1/"

#: Произвольный JSON-объект — тело action'а, legacy-алиаса и webhook'а.
_JSON_OBJECT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": True,
    "description": "Произвольный JSON-объект (payload операции).",
}

#: Тело GraphQL-запроса.
_GRAPHQL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "variables": {"type": "object", "additionalProperties": True},
        "operationName": {"type": "string"},
    },
    "required": ["query"],
}

#: Тело SAML-ACS: форма с SAMLResponse.
_SAML_FORM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"SAMLResponse": {"type": "string"}},
    "required": ["SAMLResponse"],
}

#: Эндпоинты, читающие тело вручную (FastAPI не может вывести
#: ``requestBody`` — параметра тела в сигнатуре нет).
#:
#: Ключ — правило совпадения пути (``prefix``/``suffix``), значение —
#: ``(media-type, схема тела)``.
#:
#: Правила, а не точные пути: монтирование GraphQL/SOAP/webhook-роутов
#: зависит от конфигурации приложения (``/api/v1/graphql`` и ``/graphql``),
#: и точный список путей молча расходился бы с реальной схемой.
_RAW_BODY_RULES: tuple[tuple[str, str, str, dict[str, Any]], ...] = (
    (
        "suffix",
        "/storage/upload-stream",
        "application/octet-stream",
        {"type": "string", "format": "binary"},
    ),
    ("suffix", "/saml/acs", "application/x-www-form-urlencoded", _SAML_FORM_SCHEMA),
    ("suffix", "/graphql", "application/json", _GRAPHQL_SCHEMA),
    ("prefix", "/soap", "application/xml", {"type": "string"}),
    ("prefix", "/express/", "application/json", _JSON_OBJECT_SCHEMA),
    ("prefix", "/webhooks/", "application/json", _JSON_OBJECT_SCHEMA),
)

#: Операции без тела, у которых нет ни path-, ни query-параметров.
#:
#: Для каждой — причина, по которой тело контрактом не предусмотрено.
#: Операция вне этого списка (и вне остальных правил) считается
#: недокументированной и ломает гейт.
_NO_BODY_BY_CONTRACT: dict[str, str] = {
    "/api/v1/admin/cache/invalidate": (
        "Сброс кэша целиком — операция не принимает ни тела, ни параметров."
    ),
    "/api/v1/admin/config/reload": (
        "Перезагрузка конфигурации — операция не принимает ни тела, ни параметров."
    ),
    "/api/v1/admin/ip-restriction/reload": (
        "Перезагрузка правил IP-ограничения — операция не принимает ни тела, "
        "ни параметров."
    ),
    "/api/v1/storage/delete_file/": (
        "Legacy-контракт action'а: операция не принимает ни тела, ни "
        "объявленных параметров."
    ),
    "/api/v1/auth/step-up-request": (
        "Выдача step-up-токена по IP-контексту — тело не принимается."
    ),
}

#: Реальные 4xx-ответы отдельных операций.
#:
#: Ключ — ``(метод, путь)``, значение — ``{код: описание}``. Для мутаций
#: под auth-guard'ом 401/403 добавляются автоматически
#: (``openapi_security.annotate_error_responses``); здесь — только те
#: ответы, которые даёт не auth-слой.
_OPERATION_ERRORS: dict[tuple[str, str], dict[str, str]] = {
    ("post", "/api/v1/storage/upload_file"): {
        "413": "Файл превышает лимит загрузки (MAX_UPLOAD_BYTES).",
        "415": "Content-Type файла не входит в allowlist загрузки.",
    },
    ("post", "/api/v1/storage/upload-stream"): {
        "413": "Тело превышает лимит потоковой загрузки (MAX_STREAM_UPLOAD_BYTES).",
        "415": "Content-Type не входит в allowlist загрузки.",
    },
    ("post", "/api/v1/auth/login"): {
        "401": "Отсутствует или недействителен X-Step-Up-Token (LoginStepUpMiddleware).",
        "429": "Превышен лимит попыток входа (rate-limit per IP).",
    },
    ("post", "/api/v1/auth/step-up-request"): {
        "429": "Превышен лимит запросов step-up-токена (rate-limit per IP)."
    },
}

#: Тело ответа ``HTTPException`` (FastAPI): ``{"detail": "..."}``.
_FASTAPI_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"detail": {"type": "string"}},
    "required": ["detail"],
}

#: Тело ответа middleware-слоя (``LoginStepUpMiddleware``):
#: ``{"error": "...", "detail": "..."}``.
_MIDDLEWARE_ERROR_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"error": {"type": "string"}, "detail": {"type": "string"}},
}


def _path_placeholders(path: str) -> list[str]:
    """Собрать имена path-параметров из шаблона пути."""
    return [
        name
        for name in re.findall(r"{([^{}]+)}", path)
        if not name.startswith(":") and "=" not in name
    ]


def _request_body(media_type: str, body_schema: dict[str, Any]) -> dict[str, Any]:
    """Собрать блок ``requestBody`` для media-type и схемы тела."""
    return {"required": False, "content": {media_type: {"schema": body_schema}}}


def _error_response(description: str, body_schema: dict[str, Any]) -> dict[str, Any]:
    """Собрать описание 4xx-ответа с inline-схемой тела."""
    return {
        "description": description,
        "content": {"application/json": {"schema": body_schema}},
    }


def _resolve_request_body(path: str) -> dict[str, Any] | None:
    """Определить ``requestBody`` для пути.

    Args:
        path: Путь операции (с префиксом приложения).

    Returns:
        Блок ``requestBody`` либо ``None``, если тело контрактом
        не предусмотрено.

    """
    if path.startswith(AUTO_ACTION_PREFIX):
        # Auto-registered action: ``await request.json()`` (POST/PUT/PATCH).
        return _request_body("application/json", _JSON_OBJECT_SCHEMA)
    for kind, marker, media_type, body_schema in _RAW_BODY_RULES:
        matched = path.startswith(marker) if kind == "prefix" else path.endswith(marker)
        if matched:
            return _request_body(media_type, body_schema)
    return None


def annotate_request_bodies(schema: dict[str, Any]) -> dict[str, Any]:
    """Дописать ``requestBody`` мутациям, чьё тело принимается, но не описано.

    FastAPI выводит ``requestBody`` только для параметров тела в сигнатуре
    обработчика. Обработчики, читающие тело вручную, тела в схеме не имеют.

    Args:
        schema: OpenAPI-схема.

    Returns:
        Та же схема с дописанными ``requestBody``.

    """
    added = 0
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _BODY_METHODS or not isinstance(operation, dict):
                continue
            if "requestBody" in operation:
                continue
            request_body = _resolve_request_body(path)
            if request_body is None:
                continue
            operation["requestBody"] = request_body
            added += 1

    _logger.info(
        "openapi_completeness.request_bodies_added", extra={"operations": added}
    )
    return schema


def annotate_path_parameters(schema: dict[str, Any]) -> dict[str, Any]:
    """Описать path-параметры, объявленные в шаблоне пути, но не в схеме.

    Часть action-роутов объявляет placeholder в пути (``/scan_file/{file_uuid}``),
    но не биндит его в сигнатуре обработчика: FastAPI такой параметр в
    ``parameters`` не выводит, хотя маршрут без сегмента не совпадёт. Клиент,
    сгенерированный из спецификации, не знает, что сегмент обязателен.

    Args:
        schema: OpenAPI-схема.

    Returns:
        Та же схема с дописанными path-параметрами.

    """
    added = 0
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        placeholders = _path_placeholders(path)
        if not placeholders:
            continue
        for operation in path_item.values():
            if not isinstance(operation, dict) or "responses" not in operation:
                continue
            parameters = operation.setdefault("parameters", [])
            if not isinstance(parameters, list):
                continue
            declared = {
                parameter.get("name")
                for parameter in parameters
                if isinstance(parameter, dict) and parameter.get("in") == "path"
            }
            for name in placeholders:
                if name in declared:
                    continue
                parameters.append(
                    {
                        "name": name,
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                        "description": (
                            "Параметр пути (обязателен для совпадения маршрута)."
                        ),
                    }
                )
                added += 1

    _logger.info(
        "openapi_completeness.path_parameters_added", extra={"parameters": added}
    )
    return schema


def annotate_legacy_aliases(app: FastAPI, schema: dict[str, Any]) -> dict[str, Any]:
    """Опубликовать скрытые legacy-алиасы как ``deprecated``-операции.

    Алиасы зарегистрированы с ``include_in_schema=False``: маршруты живые,
    но спецификация о них молчала. Теперь они описаны и помечены
    ``deprecated`` — правда вместо молчания.

    Args:
        app: FastAPI-приложение (нужен для обхода скрытых маршрутов).
        schema: OpenAPI-схема.

    Returns:
        Та же схема с опубликованными legacy-операциями.

    """
    paths = schema.setdefault("paths", {})
    published = 0
    for context in iter_route_contexts(app.routes):
        route = context.route
        if not isinstance(route, APIRoute) or route.include_in_schema:
            continue
        path = context.path_format
        if not path or not path.startswith(_API_PREFIX):
            continue
        methods = sorted(
            method.lower()
            for method in (route.methods or set())
            if method.lower() in _HTTP_METHODS
        )
        if not methods:
            continue
        path_item = paths.setdefault(path, {})
        for method in methods:
            operation = path_item.setdefault(method, {})
            operation["deprecated"] = True
            operation["tags"] = ["Legacy"]
            operation["summary"] = f"Legacy-алиас (deprecated): {method.upper()} {path}"
            operation["description"] = (
                "Back-compat алиас, зарегистрированный вне схемы "
                "(include_in_schema=False). Оставлен для старых клиентов "
                "(Streamlit). Канонические пути: /api/v1/order/*, "
                "/api/v1/user/*, /api/v1/file/*."
            )
            operation["x-legacy-alias"] = True
            responses = operation.setdefault("responses", {})
            responses.setdefault(
                "200",
                _error_response(
                    "Результат dispatch'а legacy-алиаса.",
                    {"type": "object", "additionalProperties": True},
                ),
            )
            responses.setdefault(
                "404",
                _error_response("Action не найден в реестре.", _FASTAPI_ERROR_SCHEMA),
            )
            if method in _BODY_METHODS:
                # ``legacy_aliases._dispatch_with`` читает JSON-тело вручную.
                operation.setdefault(
                    "requestBody",
                    _request_body("application/json", _JSON_OBJECT_SCHEMA),
                )
            published += 1

    _logger.info(
        "openapi_completeness.legacy_aliases_published", extra={"operations": published}
    )
    return schema


def annotate_operation_errors(schema: dict[str, Any]) -> dict[str, Any]:
    """Дописать реальные 4xx-ответы отдельных операций.

    Для мутаций под auth-guard'ом 401/403 добавляет
    ``openapi_security.annotate_error_responses``; здесь — только ответы
    не-auth слоя: лимиты загрузки (413/415) и step-up/rate-limit (401/429).

    Args:
        schema: OpenAPI-схема.

    Returns:
        Та же схема с дописанными 4xx-ответами.

    """
    annotated = 0
    for (method, path), codes in _OPERATION_ERRORS.items():
        path_item = schema.get("paths", {}).get(path)
        if not isinstance(path_item, dict):
            continue
        operation = path_item.get(method.lower())
        if not isinstance(operation, dict):
            continue
        responses = operation.setdefault("responses", {})
        if not isinstance(responses, dict):
            continue
        for code, description in codes.items():
            if code in responses:
                continue
            body_schema = (
                _FASTAPI_ERROR_SCHEMA
                if code in {"413", "415"}
                else _MIDDLEWARE_ERROR_SCHEMA
            )
            responses[code] = _error_response(description, body_schema)
            annotated += 1

    _logger.info(
        "openapi_completeness.operation_errors_annotated",
        extra={"responses": annotated},
    )
    return schema


def classify_missing_request_body(
    operation: dict[str, Any], method: str, path: str
) -> str | None:
    """Объяснить, почему у мутации нет ``requestBody``.

    Args:
        operation: Операция OpenAPI (path-item).
        method: HTTP-метод операции (нижний регистр).
        path: Путь операции.

    Returns:
        Причину отсутствия ``requestBody`` либо ``None``, если операция
        не документирована (её нельзя молча пропустить).

    """
    kinds = {
        parameter.get("in")
        for parameter in operation.get("parameters", [])
        if isinstance(parameter, dict)
    }
    if "path" in kinds:
        return "Идентификатор передаётся в пути — тело контрактом не предусмотрено."
    if "query" in kinds:
        return "Параметры передаются в query — тело контрактом не предусмотрено."
    if path.startswith(AUTO_ACTION_PREFIX):
        return "Auto-registered action: payload передаётся в query (метод без тела)."
    return _NO_BODY_BY_CONTRACT.get(path)


def undocumented_mutations_without_request_body(
    schema: dict[str, Any],
) -> list[tuple[str, str]]:
    """Собрать мутации без ``requestBody`` и без документированной причины.

    Пустой список — условие «исключения не растут молча».

    Args:
        schema: OpenAPI-схема.

    Returns:
        Список пар ``(method, path)``.

    """
    result: list[tuple[str, str]] = []
    for path, path_item in schema.get("paths", {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _MUTATION_METHODS or not isinstance(
                operation, dict
            ):
                continue
            if "requestBody" in operation:
                continue
            if classify_missing_request_body(operation, method.lower(), path) is None:
                result.append((method.lower(), path))
    return sorted(result)


def annotate_completeness(app: FastAPI, schema: dict[str, Any]) -> dict[str, Any]:
    """Довести схему до полноты: legacy-алиасы, ``requestBody``, 4xx.

    Args:
        app: FastAPI-приложение.
        schema: OpenAPI-схема (уже аннотированная ``security``).

    Returns:
        Та же схема с дополнениями.

    """
    schema = annotate_legacy_aliases(app, schema)
    schema = annotate_path_parameters(schema)
    schema = annotate_request_bodies(schema)
    return annotate_operation_errors(schema)
