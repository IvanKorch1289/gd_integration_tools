from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp


__all__ = ("SecurityHeadersMiddleware",)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware для добавления HTTP-заголовков безопасности.

    Добавляет набор HTTP-заголовков, повышающих безопасность приложения:
    - Защита от атак, таких как XSS, clickjacking, MIME-sniffing
    - Контроль доступа к функциям браузера
    - Управление политикой безопасности контента
    """

    def __init__(self, app: ASGIApp):
        """
        Инициализирует middleware.

        Аргументы:
            app (ASGIApp): ASGI-приложение (FastAPI/Starlette)
        """
        super().__init__(app)
        self._security_headers = {
            "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
            "Content-Security-Policy": "default-src 'self'",
            "Permissions-Policy": "geolocation=(), microphone=()",
        }

    async def dispatch(self, request, call_next):
        """
        Обрабатывает запрос, добавляя заголовки безопасности к ответу.

        Аргументы:
            request: Входящий HTTP-запрос
            call_next: Следующий middleware/обработчик

        Возвращает:
            Ответ с добавленными HTTP-заголовками безопасности
        """
        response = await call_next(request)
        response.headers.update(self._security_headers)
        return response
