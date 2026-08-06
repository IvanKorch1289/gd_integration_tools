"""Единая модель ошибок приложения.

Все ошибки наследуются от ``BaseError`` и автоматически
содержат HTTP status code, сообщение и метод ``to_dict()``
для протоколо-агностичной сериализации.
"""

import json
import uuid
from typing import Any

from starlette import status
from starlette.types import Scope

__all__ = (
    "AuthenticationError",
    "AuthorizationError",
    "BadRequestError",
    "BaseError",
    "DatabaseError",
    "NotFoundError",
    "ProductionWiringError",
    "RouteDisabledError",
    "RoutePermissionDeniedError",
    "ServiceError",
    "TenantContextRequiredError",
    "UnprocessableError",
    "build_error_envelope",
)


def build_error_envelope(
    code: str,
    detail: str,
    *,
    scope: Scope | None = None,
    error_id: str | None = None,
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
            message=message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
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
    """Маршрут декларирует ``requires_permission``, но principal не имеет нужной role/scope.

    Sprint 1: route-wide permission enforcement (V22 R-V15-1 / K-ARCH-1).
    ``DsлService.dispatch`` валит pipeline с этой ошибкой при наличии
    ненулевого ``pipeline.security`` и отсутствии требуемой permission
    у ``ExecutionContext.principal``.

    Отличие от :class:`AuthorizationError`: эта ошибка возникает
    на уровне DSL pipeline (route-wide), а не endpoint-guard.
    """

    def __init__(
        self,
        *_: Any,
        route_id: str = "",
        principal: str = "",
        required_permissions: tuple[str, ...] = (),
        reason: str = "",
    ) -> None:
        self.route_id = route_id
        self.principal = principal
        self.required_permissions = required_permissions
        self.reason = reason
        super().__init__(
            message=(
                f"Route '{route_id}' requires permissions {list(required_permissions)} "
                f"but principal '{principal}' lacks them"
                + (f" (reason: {reason})" if reason else "")
            ),
            status_code=status.HTTP_403_FORBIDDEN,
        )
