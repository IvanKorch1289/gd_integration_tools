import traceback

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware


__all__ = ("ExceptionHandlerMiddleware",)


class ExceptionHandlerMiddleware(BaseHTTPMiddleware):
    """
    Middleware для глобальной обработки исключений в приложении.
    Заменяет декоратор @handle_routes_errors, перехватывая все исключения
    на уровне middleware.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:
            # Формируем детали ошибки
            error_message = f"{type(exc).__name__} ({exc.__class__.__module__}): {str(exc)}"
            traceback_str = "".join(
                traceback.format_exception(type(exc), exc, exc.__traceback__)
            )

            # Создаем структуру ответа
            error_data = {
                "message": error_message,
                "traceback": traceback_str,
                "hasErrors": True,
            }

            # Возвращаем JSON-ответ с HTTP 500
            return JSONResponse(status_code=500, content=error_data)
