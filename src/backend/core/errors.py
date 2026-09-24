"""Единая модель ошибок приложения.

Содержит два слоя:

1. ``BaseError`` и конкретные исключения (``NotFoundError``,
   ``AuthenticationError`` и т.д.) — Python-исключения, которые
   бросаются в коде и ловятся middleware / transport-handler'ами.

2. ``DomainProblem`` (W11 P0-4, ADR-0337) — transport-neutral
   dataclass, который является **канонической формой ошибки**
   для сериализации. Содержит transport adapters (to_rfc9457,
   to_graphql_extensions, to_grpc_status, to_soap_fault, to_mcp_error,
   to_dlq_envelope) — каждый transport-adapter преобразует
   DomainProblem в свой формат.

Использование::

    # Python raise (конкретные случаи):
    raise NotFoundError(message="Order not found")

    # Transport-neutral representation (для cross-protocol serialization):
    problem = DomainProblem.from_exception(exc)
    http_response = problem.to_rfc9457(instance="/orders/1")
    graphql_ext = problem.to_graphql_extensions()
"""

import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping

from starlette import status
from starlette.types import Scope

__all__ = (
    "AuthenticationError",
    "AuthorizationError",
    "BadRequestError",
    "BaseError",
    "DatabaseError",
    "DomainProblem",
    "NotFoundError",
    "ProblemCategory",
    "ProductionWiringError",
    "RouteDisabledError",
    "RoutePermissionDeniedError",
    "ServiceError",
    "TenantContextRequiredError",
    "UnprocessableError",
    "build_error_envelope",
)


def build_error_envelope(
    code: str, detail: str, *, scope: Scope | None = None, error_id: str | None = None
) -> dict[str, Any]:
    """Собирает унифицированный error envelope для HTTP/middleware ответов.

    Возвращает dict с ключами:
    - code: машинно-читаемый код ошибки
    - detail: человеко-читаемое описание
    - error_id: UUID4 (генерируется, если не передан явно)
    - correlation_id: из scope['state']['correlation_id'], если есть
    - request_id: из scope, если есть

    Используется в middleware для унификации формата ошибок
    (cycle 35 A2, инициатива error-envelope unification).
    """
    correlation_id: str | None = None
    request_id: str | None = None
    if scope is not None:
        state = scope.get("state") or {}
        if isinstance(state, dict):
            cid = state.get("correlation_id")
            if isinstance(cid, str):
                correlation_id = cid
        rid = scope.get("request_id")
        if isinstance(rid, str):
            request_id = rid
    return {
        "code": code,
        "detail": detail,
        "error_id": error_id or str(uuid.uuid4()),
        "correlation_id": correlation_id,
        "request_id": request_id,
    }


# Маппинг HTTP → gRPC статусов для multi-protocol ошибок.
_HTTP_TO_GRPC_STATUS: dict[int, int] = {
    status.HTTP_400_BAD_REQUEST: 3,  # INVALID_ARGUMENT
    status.HTTP_401_UNAUTHORIZED: 16,  # UNAUTHENTICATED
    status.HTTP_403_FORBIDDEN: 7,  # PERMISSION_DENIED
    status.HTTP_404_NOT_FOUND: 5,  # NOT_FOUND
    status.HTTP_422_UNPROCESSABLE_CONTENT: 3,  # INVALID_ARGUMENT (starlette 1.3.0+)
    status.HTTP_500_INTERNAL_SERVER_ERROR: 13,  # INTERNAL
    status.HTTP_503_SERVICE_UNAVAILABLE: 14,  # UNAVAILABLE
}


class BaseError(Exception):
    """Базовый класс для всех ошибок приложения.

    Поддерживает multi-protocol сериализацию:
    - ``to_dict()`` — JSON для REST/WebSocket/GraphQL
    - ``grpc_status_code`` — gRPC status code
    - ``soap_fault_code`` — SOAP Fault code

    Attrs:
        message: Сообщение об ошибке.
        status_code: HTTP-статус код.
    """

    def __init__(
        self,
        *_: Any,
        message: str = "",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        self.message: str = message
        self.status_code: int = status_code
        super().__init__(message)

    @property
    def grpc_status_code(self) -> int:
        """Возвращает gRPC status code по HTTP status code."""
        return _HTTP_TO_GRPC_STATUS.get(self.status_code, 13)

    @property
    def soap_fault_code(self) -> str:
        """Возвращает SOAP Fault code по HTTP status code."""
        if self.status_code < 500:
            return "Client"
        return "Server"

    def to_dict(self, *, include_type: bool = False) -> dict[str, Any]:
        """Сериализует ошибку в словарь.

        Args:
            include_type: Включить имя класса ошибки.

        Returns:
            Словарь с полями ``message``, ``status_code``
            и опционально ``error_type``.

        """
        result: dict[str, Any] = {
            "message": self.message,
            "status_code": self.status_code,
            "hasErrors": True,
        }
        if include_type:
            result["error_type"] = self.__class__.__name__
        return result


class BadRequestError(BaseError):
    """Некорректный запрос (400 Bad Request)."""

    def __init__(self, *_: Any, message: str = "Bad request") -> None:
        super().__init__(message=message, status_code=status.HTTP_400_BAD_REQUEST)


class UnprocessableError(BaseError):
    """Ошибка валидации данных (422 Unprocessable Entity)."""

    def __init__(self, *_: Any, message: str = "Validation error") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,  # starlette 1.3.0+
        )


class NotFoundError(BaseError):
    """Ресурс не найден (404 Not Found)."""

    def __init__(self, *_: Any, message: str = "Not found") -> None:
        super().__init__(message=message, status_code=status.HTTP_404_NOT_FOUND)


class DatabaseError(BaseError):
    """Ошибка базы данных (500 Internal Server Error)."""

    def __init__(self, *_: Any, message: str = "Database error") -> None:
        super().__init__(
            message=message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class ProductionWiringError(BaseError):
    """Composition root имеет незавершённую/неконсистентную продакшн-конфигурацию.

    B-20 fix (cycle 38): поднимается при ``engine_enabled=True`` без
    сконфигурированных policy-движков (OPA/Casbin) — fake-active security
    в production-профиле запрещена. Также подходит для любых других
    composition-root случаев, когда мастер-флаг ``enabled=True`` обязан
    сопровождаться зависимыми настройками, но они пусты.

    Используется в :func:`src.backend.plugins.composition.di.register_app_state`
    для fail-loud при ``policy.engine_enabled=True`` и пустых
    ``policy.opa_url`` / ``policy.casbin_model_path``.
    """

    def __init__(
        self,
        *_: Any,
        message: str = "Production wiring is incomplete",
        missing: tuple[str, ...] = (),
    ) -> None:
        self.missing: tuple[str, ...] = missing
        if missing:
            message = f"{message} (missing: {list(missing)})"
        super().__init__(
            message=message, status_code=status.HTTP_503_SERVICE_UNAVAILABLE
        )


class AuthenticationError(BaseError):
    """Ошибка аутентификации (401 Unauthorized)."""

    def __init__(self, *_: Any, message: str = "Authentication error") -> None:
        super().__init__(message=message, status_code=status.HTTP_401_UNAUTHORIZED)


class AuthorizationError(BaseError):
    """Ошибка авторизации (403 Forbidden)."""

    def __init__(self, *_: Any, message: str = "Authorization error") -> None:
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN)


class ServiceError(BaseError):
    """Ошибка взаимодействия с внешними сервисами.

    Наследуется от ``BaseError`` (а не ``Exception``),
    чтобы поддерживать единую модель сериализации.
    """

    def __init__(self, detail: str = "Ошибка обработки запроса") -> None:
        self.detail = detail
        super().__init__(
            message=detail, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class RouteDisabledError(BaseError):
    """Маршрут отключён feature-флагом (503 Service Unavailable)."""

    def __init__(self, *_: Any, route_id: str = "", feature_flag: str = "") -> None:
        self.route_id = route_id
        self.feature_flag = feature_flag
        super().__init__(
            message=f"Route '{route_id}' is disabled by feature flag '{feature_flag}'",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )


class TenantContextRequiredError(BaseError):
    """Маршрут декларирует ``tenant_aware=True``, но tenant_id отсутствует.

    K-ARCH-4 (Sprint 17): pipeline с ``tenant_aware=True`` требует, чтобы
    хотя бы один из источников вернул tenant_id:

    * :func:`src.backend.core.request_context.RequestContext.current` →
      ``.tenant_id``;
    * :func:`src.backend.core.tenancy.current_tenant` → ``.tenant_id``.

    Если оба источника пусты — ExecutionEngine валит pipeline с этой
    ошибкой ДО первого процессора, предотвращая утечку данных между
    тенантами.
    """

    def __init__(self, *_: Any, route_id: str = "") -> None:
        self.route_id = route_id
        super().__init__(
            message=(
                f"Route '{route_id}' declares tenant_aware=True but no "
                "tenant_id available in RequestContext or TenantContext. "
                "Ensure X-Tenant-ID header is set and TenantMiddleware/"
                "RequestContextMiddleware are wired in the middleware chain."
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class RoutePermissionDeniedError(BaseError):
    """K3 S19 W3: route-level ``requires_permission`` не выполнен.

    Маршрут декларирует ``[security] requires_permission`` в ``route.toml``,
    но :func:`src.backend.services.routes.route_authz.check_route_permission`
    вернул ``allowed=False``. Возможные причины:

    * principal не имеет требуемой роли/scope;
    * :class:`AuthorizationGateway` не зарегистрирован в
      ``ai_agent._authz_gateway`` (fail-closed);
    * feature-flag ``route_authz_requires_permission`` не позволяет
      выполнение (policy вернёт deny);
    * auth-контекст запроса не передал ``principal`` / ``permissions``
      в :class:`src.backend.dsl.engine.context.ExecutionContext`.

    HTTP-статус 403. Приложение НЕ должно вызывать pipeline до устранения.
    """

    def __init__(self, *_: Any, route_id: str = "", reason: str = "") -> None:
        self.route_id = route_id
        self.reason = reason
        super().__init__(
            message=(
                f"Route '{route_id}' requires permissions not satisfied: {reason}"
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )


# ──────────────────── W11 P0-4: DomainProblem (transport-neutral) ────────────────────


class ProblemCategory(str, Enum):
    """Канонические категории ошибок (транспорт-агностичная таксономия).

    Значения совпадают с ``entrypoints/graphql/canonical_errors.py::ErrorCategory``
    для совместимости — DomainProblem и GraphQL extensions.category используют
    один и тот же enum, что позволяет клиентам единообразно обрабатывать ошибки
    вне зависимости от transport.

    Допустимые категории (8):
        VALIDATION        — некорректные данные (HTTP 400/422)
        AUTHENTICATION    — отсутствует/неверный credential (HTTP 401)
        AUTHORIZATION     — authenticated, но permission denied (HTTP 403)
        NOT_FOUND         — ресурс не найден (HTTP 404)
        CONFLICT          — состояние конфликтует с операцией (HTTP 409)
        RATE_LIMIT        — превышен лимит запросов (HTTP 429)
        UNAVAILABLE       — сервис временно недоступен (HTTP 503)
        INTERNAL          — внутренняя ошибка (HTTP 500)
    """

    VALIDATION = "validation"
    AUTHENTICATION = "authentication"
    AUTHORIZATION = "authorization"
    NOT_FOUND = "not_found"
    CONFLICT = "conflict"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    INTERNAL = "internal"


# Маппинг ProblemCategory → дефолтный HTTP status code (для to_rfc9457).
_CATEGORY_TO_STATUS: Mapping[ProblemCategory, int] = {
    ProblemCategory.VALIDATION: status.HTTP_422_UNPROCESSABLE_CONTENT,
    ProblemCategory.AUTHENTICATION: status.HTTP_401_UNAUTHORIZED,
    ProblemCategory.AUTHORIZATION: status.HTTP_403_FORBIDDEN,
    ProblemCategory.NOT_FOUND: status.HTTP_404_NOT_FOUND,
    ProblemCategory.CONFLICT: status.HTTP_409_CONFLICT,
    ProblemCategory.RATE_LIMIT: status.HTTP_429_TOO_MANY_REQUESTS,
    ProblemCategory.UNAVAILABLE: status.HTTP_503_SERVICE_UNAVAILABLE,
    ProblemCategory.INTERNAL: status.HTTP_500_INTERNAL_SERVER_ERROR,
}

# Категории, которые можно retry-ить на transport-уровне (backoff с jitter).
_RETRYABLE_CATEGORIES: frozenset[ProblemCategory] = frozenset(
    {ProblemCategory.UNAVAILABLE, ProblemCategory.RATE_LIMIT, ProblemCategory.INTERNAL}
)

# HTTP → gRPC status code (расширение существующего _HTTP_TO_GRPC_STATUS).
# Используем те же значения для консистентности с BaseError.grpc_status_code.
_CATEGORY_TO_GRPC: Mapping[ProblemCategory, int] = {
    ProblemCategory.VALIDATION: 3,  # INVALID_ARGUMENT
    ProblemCategory.AUTHENTICATION: 16,  # UNAUTHENTICATED
    ProblemCategory.AUTHORIZATION: 7,  # PERMISSION_DENIED
    ProblemCategory.NOT_FOUND: 5,  # NOT_FOUND
    ProblemCategory.CONFLICT: 6,  # ALREADY_EXISTS
    ProblemCategory.RATE_LIMIT: 8,  # RESOURCE_EXHAUSTED
    ProblemCategory.UNAVAILABLE: 14,  # UNAVAILABLE
    ProblemCategory.INTERNAL: 13,  # INTERNAL
}


@dataclass(frozen=True, slots=True)
class DomainProblem:
    """Transport-neutral каноническое представление ошибки.

    Стратегический анализ 2026-09-22 (timestamp 1790089356160) выявил gap:
    «Нужен объект уровня core: ``DomainProblem`` … Transport adapters должны
    только преобразовывать его в RFC 9457, GraphQL extensions, gRPC Status,
    SOAP Fault, MCP error или DLQ envelope».

    Этот dataclass реализует эту модель. Каждый transport-adapter возвращает
    чистый dict (без side-effects), что упрощает тестирование и избавляет от
    необходимости поддерживать несколько параллельных обработчиков ошибок
    (Sprint 3 audit finding: GraphQL-specific canonical_errors не покрывает
    другие транспорты).

    Attributes:
        code: Машино-читаемый код ошибки (e.g., "ORDER_NOT_FOUND", "TENANT_REQUIRED").
            Должен быть SCREAMING_SNAKE_CASE, стабильным между версиями API
            (breaking change если меняется).
        category: Каноническая категория (``ProblemCategory``). Определяет retryable,
            HTTP status code по умолчанию, gRPC status code и т.д.
        title: Человеко-читаемое краткое описание (≤ 120 символов, на английском
            для совместимости с i18n fallback'ами клиентов).
        retryable: True если ошибка transient и можно retry-ить с backoff.
            ``None`` (default) — вычисляется из category. Explicit ``True`` /
            ``False`` перебивает category default.
        status_code: HTTP-эквивалент status code. Если не задан, вычисляется
            из category. Используется REST adapter'ом.
        safe_details: Дополнительные non-sensitive детали (e.g., {"resource": "order",
            "resource_id": "123"}). НЕ должны содержать credentials, PII или
            internal stack traces — это нарушит security boundary.
        correlation_id: ID для distributed tracing. Устанавливается middleware
            (idempotency, correlation-id) и пробрасывается во все транспорты.
        cause: Оригинальное исключение (НЕ сериализуется, только для in-process
            logging / debugging). marked ``compare=False, repr=False`` чтобы
            не ломать dataclass equality/hash.

    See Also:
        ADR-0337 — canonical error contract.
    """

    code: str
    category: ProblemCategory
    title: str
    retryable: bool | None = field(default=None)
    status_code: int = field(default=0)  # 0 = auto-derive from category
    safe_details: Mapping[str, Any] = field(default_factory=dict)
    correlation_id: str = field(default="")
    cause: BaseException | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        """Валидация инвариантов DomainProblem."""
        if not self.code:
            raise ValueError("DomainProblem.code обязателен")
        if not self.code.replace("_", "").isalnum() or not self.code.isupper():
            raise ValueError(
                f"DomainProblem.code должен быть SCREAMING_SNAKE_CASE, "
                f"получено: {self.code!r}"
            )
        # Auto-derive status_code если 0
        if self.status_code == 0:
            object.__setattr__(self, "status_code", _CATEGORY_TO_STATUS[self.category])

    @property
    def is_retryable(self) -> bool:
        """True если ошибку можно retry-ить.

        Семантика:
            - ``retryable=None`` (default) → вычисляется из category.
            - Explicit ``True`` или ``False`` → перебивает category default.
        """
        if self.retryable is not None:
            return self.retryable
        return self.category in _RETRYABLE_CATEGORIES

    # ─────────── Transport adapters ───────────

    def to_rfc9457(self, instance: str = "") -> dict[str, Any]:
        """Преобразует в RFC 9457 Problem Details for HTTP APIs.

        См. https://www.rfc-editor.org/rfc/rfc9457

        Args:
            instance: URI-reference, идентифицирующий конкретное вхождение
                проблемы (e.g., "/orders/123").

        Returns:
            Dict с полями ``type``, ``title``, ``status``, ``detail``,
            ``instance``, ``code``, ``category``, ``retryable``, плюс
            ``correlation_id`` если задан.
        """
        result: dict[str, Any] = {
            "type": f"https://errors.gd-integration-tools/{self.category.value}",
            "title": self.title,
            "status": self.status_code,
            "detail": self.title,  # RFC 9457: title — короткое, detail — развёрнутое
            "code": self.code,
            "category": self.category.value,
            "retryable": self.is_retryable,
        }
        if instance:
            result["instance"] = instance
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.safe_details:
            result["details"] = dict(self.safe_details)
        return result

    def to_graphql_extensions(self) -> dict[str, Any]:
        """Преобразует в GraphQL extensions (consume with GraphQLError.extensions).

        Используется в ``entrypoints/graphql/canonical_errors.py::format_graphql_error``
        для единообразия с существующей GraphQL-инфраструктурой.

        Returns:
            Dict для ``extensions`` поля GraphQL error.
        """
        result: dict[str, Any] = {
            "code": self.code,
            "status_code": self.status_code,
            "category": self.category.value,
            "retryable": self.is_retryable,
        }
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.safe_details:
            result["details"] = dict(self.safe_details)
        return result

    def to_grpc_status(self) -> tuple[int, str, dict[str, Any]]:
        """Преобразует в gRPC (StatusCode, message, details-dict).

        Returns:
            Tuple ``(grpc_status_code, message, details_dict)`` для
            ``grpc.StatusCode`` + ``trailing_metadata``.
        """
        return (
            _CATEGORY_TO_GRPC[self.category],
            self.title,
            {
                "code": self.code,
                "category": self.category.value,
                "retryable": str(self.is_retryable).lower(),
                **(
                    {"correlation_id": self.correlation_id}
                    if self.correlation_id
                    else {}
                ),
            },
        )

    def to_soap_fault(self) -> dict[str, Any]:
        """Преобразует в SOAP 1.1 Fault envelope.

        Returns:
            Dict с ``faultcode``, ``faultstring``, ``detail`` для
            ``<soap:Fault>`` элемента.
        """
        fault_code = "soap:Client" if self.status_code < 500 else "soap:Server"
        result: dict[str, Any] = {
            "faultcode": fault_code,
            "faultstring": self.title,
            "detail": {
                "code": self.code,
                "category": self.category.value,
                "retryable": self.is_retryable,
                **(
                    {"correlation_id": self.correlation_id}
                    if self.correlation_id
                    else {}
                ),
            },
        }
        if self.safe_details:
            result["detail"]["details"] = dict(self.safe_details)
        return result

    def to_mcp_error(self) -> dict[str, Any]:
        """Преобразует в MCP (Model Context Protocol) error envelope.

        MCP использует JSON-RPC 2.0 error format с ``code`` (int) и ``message``.
        Маппинг категорий на JSON-RPC codes:
            VALIDATION        → -32602 (Invalid params)
            AUTHENTICATION    → -32001 (custom: unauthenticated)
            AUTHORIZATION     → -32003 (custom: permission denied)
            NOT_FOUND         → -32004 (custom: not found)
            CONFLICT          → -32005 (custom: conflict)
            RATE_LIMIT        → -32006 (custom: rate limited)
            UNAVAILABLE       → -32007 (custom: unavailable)
            INTERNAL          → -32603 (Internal error)
        """
        _CATEGORY_TO_JSONRPC: Mapping[ProblemCategory, int] = {
            ProblemCategory.VALIDATION: -32602,
            ProblemCategory.AUTHENTICATION: -32001,
            ProblemCategory.AUTHORIZATION: -32003,
            ProblemCategory.NOT_FOUND: -32004,
            ProblemCategory.CONFLICT: -32005,
            ProblemCategory.RATE_LIMIT: -32006,
            ProblemCategory.UNAVAILABLE: -32007,
            ProblemCategory.INTERNAL: -32603,
        }
        return {
            "code": _CATEGORY_TO_JSONRPC[self.category],
            "message": self.title,
            "data": {
                "code": self.code,
                "category": self.category.value,
                "retryable": self.is_retryable,
                **(
                    {"correlation_id": self.correlation_id}
                    if self.correlation_id
                    else {}
                ),
                **({"details": dict(self.safe_details)} if self.safe_details else {}),
            },
        }

    def to_dlq_envelope(self) -> dict[str, Any]:
        """Преобразует в DLQ (Dead Letter Queue) envelope.

        DLQ envelope содержит всю информацию для replay (включая
        correlation_id для трейсинга между оригинальной и DLQ-точкой).

        Returns:
            Dict для отправки в DLQ-topic / DLQ-stream.
        """
        result: dict[str, Any] = {
            "code": self.code,
            "category": self.category.value,
            "title": self.title,
            "retryable": self.is_retryable,
            "status_code": self.status_code,
        }
        if self.correlation_id:
            result["correlation_id"] = self.correlation_id
        if self.safe_details:
            result["details"] = dict(self.safe_details)
        return result

    # ─────────── Factory methods ───────────

    @classmethod
    def from_exception(
        cls, exc: BaseException, *, correlation_id: str = ""
    ) -> "DomainProblem":
        """Строит DomainProblem из произвольного исключения.

        Если ``exc`` — ``BaseError``, использует ``status_code``,
        ``message`` и (опционально) дополнительные attrs. Категория
        вычисляется из status code.

        Иначе — generic INTERNAL с type name в code.
        """
        if isinstance(exc, BaseError):
            category = _status_to_category(exc.status_code)
            return cls(
                code=_BASE_ERROR_TO_CODE.get(
                    type(exc).__name__, type(exc).__name__.upper().replace("ERROR", "")
                ),
                category=category,
                title=exc.message or type(exc).__name__,
                status_code=exc.status_code,
                correlation_id=correlation_id,
                cause=exc,
            )
        # Generic exception (не BaseError)
        return cls(
            code="INTERNAL_ERROR",
            category=ProblemCategory.INTERNAL,
            title=str(exc) or type(exc).__name__,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            correlation_id=correlation_id,
            cause=exc,
        )

    @classmethod
    def from_base_error(
        cls,
        exc: "BaseError",
        *,
        category: ProblemCategory | None = None,
        correlation_id: str = "",
    ) -> "DomainProblem":
        """Явное преобразование ``BaseError`` → ``DomainProblem``.

        Args:
            exc: BaseError-исключение.
            category: Override категории (если None — вычисляется из status_code).
            correlation_id: ID для distributed tracing.

        Returns:
            DomainProblem с cause=exc для in-process debugging.
        """
        cat = category or _status_to_category(exc.status_code)
        return cls(
            code=_BASE_ERROR_TO_CODE.get(
                type(exc).__name__, type(exc).__name__.upper().replace("ERROR", "")
            ),
            category=cat,
            title=exc.message or type(exc).__name__,
            status_code=exc.status_code,
            correlation_id=correlation_id,
            cause=exc,
        )


# Маппинг для from_exception / from_base_error.
_BASE_ERROR_TO_CODE: Mapping[str, str] = {
    "NotFoundError": "NOT_FOUND",
    "BadRequestError": "BAD_REQUEST",
    "UnprocessableError": "VALIDATION_FAILED",
    "AuthenticationError": "UNAUTHENTICATED",
    "AuthorizationError": "PERMISSION_DENIED",
    "RoutePermissionDeniedError": "ROUTE_PERMISSION_DENIED",
    "RouteDisabledError": "ROUTE_DISABLED",
    "TenantContextRequiredError": "TENANT_REQUIRED",
    "DatabaseError": "DATABASE_ERROR",
    "ProductionWiringError": "WIRING_ERROR",
    "ServiceError": "SERVICE_ERROR",
}


def _status_to_category(status_code: int) -> ProblemCategory:
    """HTTP status code → ProblemCategory (для from_exception)."""
    if status_code == status.HTTP_400_BAD_REQUEST:
        return ProblemCategory.VALIDATION
    if status_code == status.HTTP_401_UNAUTHORIZED:
        return ProblemCategory.AUTHENTICATION
    if status_code == status.HTTP_403_FORBIDDEN:
        return ProblemCategory.AUTHORIZATION
    if status_code == status.HTTP_404_NOT_FOUND:
        return ProblemCategory.NOT_FOUND
    if status_code == status.HTTP_409_CONFLICT:
        return ProblemCategory.CONFLICT
    if status_code == status.HTTP_422_UNPROCESSABLE_CONTENT:
        return ProblemCategory.VALIDATION
    if status_code == status.HTTP_429_TOO_MANY_REQUESTS:
        return ProblemCategory.RATE_LIMIT
    if status_code >= 500:
        return (
            ProblemCategory.UNAVAILABLE
            if status_code == 503
            else ProblemCategory.INTERNAL
        )
    return ProblemCategory.INTERNAL
