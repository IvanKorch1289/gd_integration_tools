"""W24 — Нормализованная модель ``ConnectorSpec`` (результат ImportGateway).

Унифицированное представление импортированного коннектора (REST/SOAP/...).
Источник может быть OpenAPI, Postman или WSDL — после парсинга все они
приводятся к единой структуре, которая затем persist-ится в
``connector_configs`` (Mongo) и регистрируется в ActionDispatcher /
SinkRegistry / SourceRegistry.

Вынесено в ``core/models/`` (а не в interfaces) потому что это плоская
data-model, не contract. Используется ImportGateway (core), ImportService
(services) и Mongo store (infrastructure).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = (
    "AuthSchemeKind",
    "AuthSpec",
    "EndpointSpec",
    "SecretRef",
    "ConnectorSpec",
)


class AuthSchemeKind(str, Enum):
    """Поддерживаемые auth-схемы (унифицировано для OpenAPI/Postman)."""

    NONE = "none"
    BASIC = "basic"
    BEARER = "bearer"
    API_KEY = "api_key"
    OAUTH2 = "oauth2"


@dataclass(slots=True)
class SecretRef:
    """Ссылка на секрет в SecretsBackend (Vault / env).

    Args:
        ref: Ключ в SecretsBackend (``${VAR}`` или ``vault:path#key``).
        hint: Подсказка для пользователя что подставить (без значения).
    """

    ref: str
    hint: str = ""


@dataclass(slots=True)
class AuthSpec:
    """Описание аутентификации для коннектора.

    Args:
        kind: Тип схемы.
        location: Где передаётся (``header`` / ``query`` / ``cookie``);
            актуально для api_key.
        param_name: Имя параметра (например ``X-API-Key``).
        secret_refs: Ссылки на секреты в SecretsBackend (token/password/etc).
            Сами значения секретов в spec'е НЕ хранятся.
        scopes: OAuth2 scopes (если применимо).
    """

    kind: AuthSchemeKind = AuthSchemeKind.NONE
    location: str = "header"
    param_name: str = ""
    secret_refs: dict[str, SecretRef] = field(default_factory=dict)
    scopes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class EndpointSpec:
    """Один endpoint (operation) импортированного коннектора.

    Args:
        operation_id: Уникальный id операции (для action-name).
        method: HTTP-метод (``GET``/``POST``/...) или ``SOAP``-action.
        path: Путь (``/v1/orders/{id}``) или SOAP-operation-name.
        summary: Краткое описание для docs.
        parameters: Список параметров (path/query/header).
        request_schema: JSON Schema тела запроса (или ``None``).
        response_schema: JSON Schema тела ответа (или ``None``).
        tags: Теги/группы (для UI/folders Postman).
    """

    operation_id: str
    method: str
    path: str
    summary: str = ""
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_schema: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    tags: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ConnectorSpec:
    """Нормализованный результат импорта.

    Args:
        name: Уникальное имя коннектора (используется как ключ в
            ``connector_configs`` Mongo).
        title: Человеко-читаемое название (info.title в OpenAPI).
        version: Версия из spec'а (info.version).
        base_url: Базовый URL.
        endpoints: Список endpoint'ов.
        auth: Auth-описание (или ``None``).
        schemas: JSON Schema definitions (components/schemas).
        source_kind: Тип исходного spec'а (postman/openapi/wsdl).
        source_hash: SHA256-hash исходного content (для idempotency).
        source_url: URL источника (или ``None``).
        metadata: Произвольные метаданные.
    """

    name: str
    title: str
    version: str
    base_url: str
    endpoints: list[EndpointSpec]
    source_kind: str
    source_hash: str
    auth: AuthSpec | None = None
    schemas: dict[str, Any] = field(default_factory=dict)
    source_url: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
