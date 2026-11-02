"""Аннотация OpenAPI-схемы реальными схемами аутентификации.

Зачем
----
Аутентификация в проекте обеспечивается **pure ASGI**-слоем
:class:`~src.backend.entrypoints.middlewares.auth_required.AuthRequiredMiddleware`,
который FastAPI не может выразить в схеме: middleware не участвует в
генерации OpenAPI. В результате опубликованная спецификация утверждала, что
аутентификация не требуется, — ``components.securitySchemes`` был пуст, и ни
у одной из 443 операций не было поля ``security``.

Измеримые последствия: в Swagger UI нет кнопки Authorize, «Try it out» не
может передать токен, а клиенты, сгенерированные из спецификации
(postman/swagger-codegen), выходят без авторизации — при том что запросы
без credentials честно получают 401.

Что делает модуль
-----------------
Схема приводится в соответствие с **фактически enforce'имым** контрактом:

* набор credential-схем берётся из тех же verifiers'ов, что вызывает
  :func:`core.auth.auth_selector.verify_request`;
* признак «public» берётся из
  :func:`auth_required.is_path_public` с каноническим
  :data:`auth_required.DEFAULT_PUBLIC_PATH_PREFIXES` — то есть из того же
  источника, которым пользуется рантайм-guard.

Модуль ничего не ужесточает и не ослабляет: он только делает спецификацию
правдивой. Ни одна проверка доступа не переносится из middleware в
спецификацию.

Что НЕ выражается в OpenAPI
---------------------------
``MTLS`` (transport-level, клиентский сертификат терминируется на
прокси) и ``EXPRESS`` / ``EXPRESS_JWT`` (заголовок ``X-Express-HUID``,
выдаётся доверенным edge-прокси). Для них не выдумываются схемы; фактический
набор методов виден в ``core.auth.auth_selector._VERIFIERS``.

Поле ``security`` описывает **слой ``AuthRequiredMiddleware``**, а не всю
цепочку. Например ``/api/v1/auth/login`` и ``/api/v1/auth/step-up-request``
входят в ``DEFAULT_PUBLIC_PATH_PREFIXES`` — их пропускает auth-guard, — и в
схеме они получают ``security: []``. Их настоящая защита — следующий слой,
``LoginStepUpMiddleware`` (``X-Step-Up-Token`` + rate-limit), который
OpenAPI выразить не может. Аналогично CSRF-cookie требование на изменяющих
методах. Схема не должна обещать больше, чем проверяет указанный слой.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from src.backend.core.logging import get_logger
from src.backend.entrypoints.api.openapi_completeness import annotate_completeness
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    is_path_public,
)

__all__ = (
    "ERROR_RESPONSE_SCHEMA_NAME",
    "SECURITY_SCHEMES",
    "annotate_error_responses",
    "annotate_openapi",
    "apply_security_to_openapi",
    "mutations_without_request_body",
)

_logger = get_logger(__name__)

#: Имя компонента схемы с унифицированным error-envelope.
ERROR_RESPONSE_SCHEMA_NAME = "ErrorEnvelope"

#: Credential-схемы, соответствующие verifiers'ам ``core.auth.auth_selector``.
#: Порядок значим только для читаемости спецификации: в массиве ``security``
#: элементы означают alternatives (OR), как и в ``verify_request``, который
#: принимает первый подошедший метод.
SECURITY_SCHEMES: dict[str, dict[str, Any]] = {
    "bearerAuth": {
        "type": "http",
        "scheme": "bearer",
        "bearerFormat": "JWT",
        "description": "RS256 JWT, AuthMethod.JWT (заголовок Authorization: Bearer).",
    },
    "apiKeyAuth": {
        "type": "apiKey",
        "in": "header",
        "name": "X-API-Key",
        # Формулировка без русских прилагательных на -ский/-ова: маскер
        # фамилий (_RU_SURNAMES в core.security.pii_masker) считает их
        # персональными данными и заменяет на ***. Сузить тот паттерн
        # без ослабления privacy-контура нельзя, поэтому текст схемы
        # подбирается так, чтобы не попадать под ложное срабатывание.
        "description": "API key (AuthMethod.API_KEY), передаётся в заголовке X-API-Key.",
    },
    "basicAuth": {
        "type": "http",
        "scheme": "basic",
        "description": "HTTP Basic, AuthMethod.BASIC.",
    },
    "samlSession": {
        "type": "apiKey",
        "in": "cookie",
        "name": "saml_session",
        "description": (
            "SAML 2.0 SSO-сессия, AuthMethod.SAML "
            "(cookie saml_session или заголовок X-SAML-Session-ID)."
        ),
    },
}

#: Alternatives для непубличных операций — те же verifiers'ы, что пробует
#: ``verify_request`` при methods=None.
_DEFAULT_REQUIREMENT: list[dict[str, list[str]]] = [
    {name: []} for name in SECURITY_SCHEMES
]

_HTTP_METHODS = ("get", "put", "post", "delete", "options", "head", "patch", "trace")

#: Методы, меняющие состояние (для них обязателен ``requestBody``-контракт).
_MUTATION_METHODS = frozenset({"post", "put", "patch", "delete"})


def annotate_openapi(schema: dict[str, Any]) -> dict[str, Any]:
    """Проставляет ``securitySchemes`` и ``security`` в готовую схему.

    Мутирует и возвращает ``schema`` — вызывается с результатом
    ``get_openapi()``.

    Args:
        schema: OpenAPI-схема, полученная от FastAPI.

    Returns:
        Та же схема с заполненными ``components.securitySchemes`` и
        ``security`` на каждой операции.

    """
    components = schema.setdefault("components", {})
    schemes = components.setdefault("securitySchemes", {})
    schemes.update(SECURITY_SCHEMES)

    public_operations = 0
    guarded_operations = 0
    for path, path_item in schema.get("paths", {}).items():
        is_public = is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES)
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            # Ни одна операция не объявляла security раньше, поэтому
            # перезапись безопасна и соответствует фактическому контракту.
            operation["security"] = [] if is_public else list(_DEFAULT_REQUIREMENT)
            if is_public:
                public_operations += 1
            else:
                guarded_operations += 1

    _logger.info(
        "openapi_security.annotated",
        extra={
            "public_operations": public_operations,
            "guarded_operations": guarded_operations,
            "security_schemes": len(SECURITY_SCHEMES),
        },
    )
    return schema


#: Описание error-envelope, который отдают middleware слоя авторизации.
_ERROR_ENVELOPE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "code": {"type": "string", "description": "Машиночитаемый код ошибки."},
        "detail": {"type": "string", "description": "Человекочитаемое описание."},
        "error_id": {"type": "string", "format": "uuid"},
        "correlation_id": {"type": ["string", "null"]},
        "request_id": {"type": ["string", "null"]},
    },
    "required": ["code", "detail"],
}


def _error_response(description: str) -> dict[str, Any]:
    """Собрать описание одного 4xx-ответа со ссылкой на error-envelope."""
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{ERROR_RESPONSE_SCHEMA_NAME}"}
            }
        },
    }


def annotate_error_responses(schema: dict[str, Any]) -> dict[str, Any]:
    """Дописать 401/403 в ответы операций, которые реально их возвращают.

    ADR-0422: до правки 205 из 443 операций не описывали ни одного 4xx-ответа,
    хотя ``AuthRequiredMiddleware`` отдаёт 401 без credentials, а
    ``CSRFMiddleware`` / admin-role guard — 403.

    Публичные пути (``DEFAULT_PUBLIC_PATH_PREFIXES``) не трогаются: auth-guard
    их пропускает, поэтому 401 там невозможен.

    Args:
        schema: OpenAPI-схема (уже проаннотированная ``security``).

    Returns:
        Та же схема с дописанными 401/403.

    """
    components = schema.setdefault("components", {})
    schemas = components.setdefault("schemas", {})
    schemas.setdefault(ERROR_RESPONSE_SCHEMA_NAME, _ERROR_ENVELOPE_SCHEMA)

    annotated = 0
    for path, path_item in schema.get("paths", {}).items():
        if is_path_public(path, DEFAULT_PUBLIC_PATH_PREFIXES):
            continue
        for method, operation in path_item.items():
            if method.lower() not in _HTTP_METHODS or not isinstance(operation, dict):
                continue
            responses = operation.setdefault("responses", {})
            if not isinstance(responses, dict):
                continue
            if "401" not in responses:
                responses["401"] = _error_response(
                    "Отсутствуют или недействительны credentials (auth-guard)."
                )
            if "403" not in responses:
                responses["403"] = _error_response(
                    "Недостаточно прав (роль/CSRF-токен)."
                )
            annotated += 1

    _logger.info(
        "openapi_security.error_responses_annotated", extra={"operations": annotated}
    )
    return schema


def mutations_without_request_body(schema: dict[str, Any]) -> list[tuple[str, str]]:
    """Собрать список мутаций без ``requestBody`` (для ADR/отчёта).

    Мутация без тела — не дефект: ``DELETE /order/delete/{id}`` и
    ``POST /storage/upload-stream`` (raw-body) не имеют JSON-тела. Список
    нужен как **документированное исключение**, а не как «неполная схема».

    Args:
        schema: OpenAPI-схема.

    Returns:
        Список пар ``(method, path)`` для мутаций без ``requestBody``.

    """
    result: list[tuple[str, str]] = []
    for path, path_item in schema.get("paths", {}).items():
        for method, operation in path_item.items():
            if method.lower() not in _MUTATION_METHODS or not isinstance(
                operation, dict
            ):
                continue
            if "requestBody" not in operation:
                result.append((method.lower(), path))
    return sorted(result, key=lambda item: (item[1], item[0]))


def apply_security_to_openapi(app: FastAPI) -> None:
    """Включает аннотацию схемы безопасности для ``app``.

    Отказ здесь не должен ронять старт приложения: спецификация — это
    документация, а не механизм контроля доступа. Ошибка логируется, и
    приложение продолжает работать с исходной схемой.

    ADR-0422: вместе с ``securitySchemes``/``security`` дописываются
    4xx-ответы (401/403) для операций под auth-guard'ом — иначе схема
    утверждала бы, что 401 невозможен.

    ADR-0423: поверх аннотаций добавляется полнота схемы
    (``openapi_completeness``): ``requestBody`` для мутаций, читающих тело
    вручную, публикация скрытых legacy-алиасов и реальные 4xx отдельных
    операций (413/415/429).

    Args:
        app: экземпляр FastAPI из :func:`create_app`.

    """
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        try:
            schema = annotate_openapi(schema)
            schema = annotate_completeness(app, schema)
            return annotate_error_responses(schema)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            # exc — причина сбоя аннотации; сам FastAPI уже отдал схему.
            _logger.warning(
                "openapi_security.annotation_failed",
                extra={"error": str(exc), "error_class": type(exc).__name__},
            )
            return schema

    app.openapi = openapi  # type: ignore[method-assign]
    # Сброс кэша FastAPI: первое обращение к /openapi.json должно получить
    # уже аннотированную схему, а не закэшированную до подключения.
    app.openapi_schema = None
