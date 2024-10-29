from typing import Any

from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette import status
from starlette.requests import Request


class BaseError(Exception):
    def __init__(
        self,
        *_: tuple[Any],
        message: str = "",
        status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR,
    ) -> None:
        self.message: str = message
        self.status_code: int = status_code

        super().__init__(message)


class BadRequestError(BaseError):
    def __init__(self, *_: tuple[Any], message: str = "Bad request") -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_400_BAD_REQUEST,
        )


class UnprocessableError(BaseError):
    def __init__(
        self, *_: tuple[Any], message: str = "Validation error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        )


class NotFoundError(BaseError):
    def __init__(self, *_: tuple[Any], message: str = "Not found") -> None:
        super().__init__(
            message=message, status_code=status.HTTP_404_NOT_FOUND
        )


class DatabaseError(BaseError):
    def __init__(
        self, *_: tuple[Any], message: str = "Database error"
    ) -> None:
        super().__init__(
            message=message, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )


class AuthenticationError(BaseError):
    def __init__(
        self, *_: tuple[Any], message: str = "Authentication error"
    ) -> None:
        super().__init__(
            message=message,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )


class AuthorizationError(BaseError):
    def __init__(
        self, *_: tuple[Any], message: str = "Authorization error"
    ) -> None:
        super().__init__(
            message=message, status_code=status.HTTP_403_FORBIDDEN
        )


# def custom_base_errors_handler(_: Request, error: BaseError) -> JSONResponse:
#     """This function is called if the BaseError was raised."""

#     response = ErrorResponseMulti(
#         results=[ErrorResponse(message=error.message.capitalize())]
#     )

#     return JSONResponse(
#         response.dict(by_alias=True),
#         status_code=error.status_code,
#     )


# def python_base_error_handler(_: Request, error: Exception) -> JSONResponse:
#     """This function is called if the Exception was raised."""

#     response = ErrorResponseMulti(
#         results=[ErrorResponse(message=f"Unhandled error: {error}")]
#     )

#     return JSONResponse(
#         content=jsonable_encoder(response.dict(by_alias=True)),
#         status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
#     )


# def pydantic_validation_errors_handler(
#     _: Request, error: RequestValidationError
# ) -> JSONResponse:
#     """This function is called if the Pydantic validation error was raised."""

#     response = ErrorResponseMulti(
#         results=[
#             ErrorResponse(
#                 message=err["msg"],
#                 path=list(err["loc"]),
#             )
#             for err in error.errors()
#         ]
#     )

#     return JSONResponse(
#         content=jsonable_encoder(response.dict(by_alias=True)),
#         status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
#     )
