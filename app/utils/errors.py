from functools import wraps
from typing import Any, Callable

from fastapi import HTTPException
from starlette import status


__all__ = (
    "NotFoundError",
    "DatabaseError",
    "BadRequestError",
    "UnprocessableError",
    "handle_db_errors",
    "handle_routes_errors",
)


class BaseError(Exception):
    """
    Базовый класс для всех пользовательских исключений.

    Атрибуты:
        message (str): Сообщение об ошибке.
        status_code (int): HTTP-статус код, связанный с ошибкой.
    """

    def __init__(
        self,
        *_: tuple[Any],
        message: str = "",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        """
        Инициализирует базовое исключение.

        Args:
            message (str): Сообщение об ошибке.
            status_code (int): HTTP-статус код, связанный с ошибкой.
        """
        self.message: str = message
        self.status_code: int = status_code
        super().__init__(message)


class BadRequestError(BaseError):
    """
    Исключение, возникающее при некорректном запросе.

    Статус код: 400 Bad Request.
    """

    def __init__(self, *_: tuple[Any], message: str = "Bad request") -> None:
        """
        Инициализирует исключение для некорректного запроса.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class UnprocessableError(BaseError):
    """
    Исключение, возникающее при ошибке валидации данных.

    Статус код: 422 Unprocessable Entity.
    """

    def __init__(self, *_: tuple[Any], message: str = "Validation error") -> None:
        """
        Инициализирует исключение для ошибки валидации.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class NotFoundError(BaseError):
    """
    Исключение, возникающее при отсутствии запрашиваемого ресурса.

    Статус код: 404 Not Found.
    """

    def __init__(self, *_: tuple[Any], message: str = "Not found") -> None:
        """
        Инициализирует исключение для отсутствующего ресурса.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(message=message, status_code=status.HTTP_404_NOT_FOUND)


class DatabaseError(BaseError):
    """
    Исключение, возникающее при ошибках в работе с базой данных.

    Статус код: 500 Internal Server Error.
    """

    def __init__(self, *_: tuple[Any], message: str = "Database error") -> None:
        """
        Инициализирует исключение для ошибок базы данных.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(
            message=message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class AuthenticationError(BaseError):
    """
    Исключение, возникающее при ошибках аутентификации.

    Статус код: 401 Unauthorized.
    """

    def __init__(self, *_: tuple[Any], message: str = "Authentication error") -> None:
        """
        Инициализирует исключение для ошибок аутентификации.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(BaseError):
    """
    Исключение, возникающее при ошибках авторизации.

    Статус код: 403 Forbidden.
    """

    def __init__(self, *_: tuple[Any], message: str = "Authorization error") -> None:
        """
        Инициализирует исключение для ошибок авторизации.

        Args:
            message (str): Сообщение об ошибке.
        """
        super().__init__(message=message, status_code=status.HTTP_403_FORBIDDEN)


def handle_db_errors(func):
    """
    Декоратор для обработки исключений в методах репозитория.

    Args:
        func: Функция, которую нужно обернуть.

    Returns:
        Callable: Обернутая функция с обработкой ошибок базы данных.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        """
        Обертка для функции, которая перехватывает исключения и преобразует их в DatabaseError.

        Args:
            *args: Позиционные аргументы функции.
            **kwargs: Именованные аргументы функции.

        Returns:
            Результат выполнения функции.

        Raises:
            DatabaseError: Если возникает ошибка при выполнении функции.
        """
        try:
            return await func(*args, **kwargs)
        except Exception as exc:
            raise DatabaseError(
                message={
                    "message": exc.message,
                    "hasErrors": True,
                }
            )

    return wrapper


def handle_routes_errors(func: Callable) -> Callable:
    """
    Декоратор для обработки исключений в методах CBV-класса.

    Этот декоратор автоматически перехватывает исключения, возникающие в методах,
    и возвращает ответ с HTTP-статусом 500 (Internal Server Error) и текстом ошибки.

    Args:
        func (Callable): Функция или метод, который нужно обернуть.

    Returns:
        Callable: Обернутая функция с обработкой исключений.

    Raises:
        HTTPException: Если в процессе выполнения функции возникает исключение,
                      возвращается HTTP-ответ с кодом 500 и текстом ошибки.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs) -> Any:
        """
        Внутренняя функция-обертка для обработки исключений.

        Args:
            *args: Аргументы, переданные в оригинальную функцию.
            **kwargs: Именованные аргументы, переданные в оригинальную функцию.

        Returns:
            Any: Результат выполнения оригинальной функции.

        Raises:
            HTTPException: Если возникает исключение, возвращается HTTP-ответ с кодом 500.
        """
        try:
            # Пытаемся выполнить оригинальную функцию
            return await func(*args, **kwargs)
        except Exception as exc:
            # Если возникает исключение, возвращаем HTTP-ответ с кодом 500
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "message": str(exc),
                    "hasErrors": True,
                },
            )

    return wrapper
