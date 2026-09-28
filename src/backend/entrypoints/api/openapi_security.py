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
from src.backend.entrypoints.middlewares.auth_required import (
    DEFAULT_PUBLIC_PATH_PREFIXES,
    is_path_public,
)

__all__ = ("SECURITY_SCHEMES", "apply_security_to_openapi", "annotate_openapi")

_logger = get_logger(__name__)

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


def apply_security_to_openapi(app: FastAPI) -> None:
    """Включает аннотацию схемы безопасности для ``app``.

    Отказ здесь не должен ронять старт приложения: спецификация — это
    документация, а не механизм контроля доступа. Ошибка логируется, и
    приложение продолжает работать с исходной схемой.

    Args:
        app: экземпляр FastAPI из :func:`create_app`.

    """
    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        schema = original_openapi()
        try:
            return annotate_openapi(schema)
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
