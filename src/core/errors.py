"""Единая модель ошибок приложения.

Все ошибки наследуются от ``BaseError`` и автоматически
содержат HTTP status code, сообщение и метод ``to_dict()``
для протоколо-агностичной сериализации.
"""

from typing import Any

from starlette import status

__all__ = (
    "BaseError",
    "BadRequestError",
    "UnprocessableError",
    "NotFoundError",
    "DatabaseError",
    "AuthenticationError",
    "AuthorizationError",
    "ServiceError",
)

# Маппинг HTTP → gRPC статусов для multi-protocol ошибок.
_HTTP_TO_GRPC_STATUS: dict[int, int] = {
    status.HTTP_400_BAD_REQUEST: 3,       # INVALID_ARGUMENT
    status.HTTP_401_UNAUTHORIZED: 16,     # UNAUTHENTICATED
    status.HTTP_403_FORBIDDEN: 7,         # PERMISSION_DENIED
    status.HTTP_404_NOT_FOUND: 5,         # NOT_FOUND
    status.HTTP_422_UNPROCESSABLE_ENTITY: 3,  # INVALID_ARGUMENT
    status.HTTP_500_INTERNAL_SERVER_ERROR: 13,  # INTERNAL
    status.HTTP_503_SERVICE_UNAVAILABLE: 14,    # UNAVAILABLE
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

    def to_dict(
        self, *, include_type: bool = False
    ) -> dict[str, Any]:
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

    def __init__(
        self, *_: Any, message: str = "Bad request"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class UnprocessableError(BaseError):
    """Ошибка валидации данных (422 Unprocessable Entity)."""

    def __init__(
        self, *_: Any, message: str = "Validation error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class NotFoundError(BaseError):
    """Ресурс не найден (404 Not Found)."""

    def __init__(
        self, *_: Any, message: str = "Not found"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_404_NOT_FOUND,
        )


class DatabaseError(BaseError):
    """Ошибка базы данных (500 Internal Server Error)."""

    def __init__(
        self, *_: Any, message: str = "Database error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class AuthenticationError(BaseError):
    """Ошибка аутентификации (401 Unauthorized)."""

    def __init__(
        self, *_: Any, message: str = "Authentication error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(BaseError):
    """Ошибка авторизации (403 Forbidden)."""

    def __init__(
        self, *_: Any, message: str = "Authorization error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_403_FORBIDDEN,
        )


class ServiceError(BaseError):
    """Ошибка взаимодействия с внешними сервисами.

    Наследуется от ``BaseError`` (а не ``Exception``),
    чтобы поддерживать единую модель сериализации.
    """

    def __init__(
        self, detail: str = "Ошибка обработки запроса"
    ) -> None:
        self.detail = detail
        super().__init__(
            message=detail,
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
