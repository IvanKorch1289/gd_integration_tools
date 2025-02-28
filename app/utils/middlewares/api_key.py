import re
from typing import List, Pattern

from fastapi import HTTPException, Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp

from app.config.settings import settings


__all__ = ("APIKeyMiddleware",)


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Middleware для проверки API-ключа в заголовках запросов.

    Обеспечивает:
    - Валидацию API-ключа для защищенных маршрутов
    - Исключение определенных маршрутов из проверки
    - Гибкую настройку через конфигурацию приложения
    """

    def __init__(self, app: ASGIApp):
        """
        Инициализирует middleware.

        Аргументы:
            app (ASGIApp): ASGI-приложение FastAPI
        """
        super().__init__(app)
        # Компилируем шаблоны исключений из настроек
        self.compiled_patterns: List[Pattern] = [
            re.compile(self._convert_pattern(pattern))
            for pattern in settings.secure.routes_without_api_key
        ]

    @staticmethod
    def _convert_pattern(pattern: str) -> str:
        """Преобразует шаблон маршрута в регулярное выражение.

        Аргументы:
            pattern (str): Шаблон маршрута (например, "/public/*")

        Возвращает:
            str: Регулярное выражение для сопоставления
        """
        return f"^{pattern.replace('*', '.*')}$"

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """Обрабатывает входящий запрос.

        Аргументы:
            request (Request): Входящий HTTP-запрос
            call_next (RequestResponseEndpoint): Следующий middleware/обработчик

        Возвращает:
            Response: HTTP-ответ

        Исключения:
            HTTPException: 401 если API-ключ отсутствует или неверен
        """
        # Пропускаем проверку для исключенных маршрутов
        if self._is_excluded_route(request.url.path):
            return await call_next(request)

        # Проверяем наличие API-ключа
        if (api_key := request.headers.get("X-API-Key")) is None:
            raise HTTPException(status_code=401, detail="Требуется API-ключ")

        # Валидируем API-ключ
        if api_key != settings.secure.api_key:
            raise HTTPException(status_code=401, detail="Неверный API-ключ")

        # Передаем запрос дальше по цепочке middleware
        return await call_next(request)

    def _is_excluded_route(self, path: str) -> bool:
        """Проверяет, исключен ли маршрут из проверки API-ключа.

        Аргументы:
            path (str): Путь запроса

        Возвращает:
            bool: True если маршрут исключен, иначе False
        """
        return any(pattern.match(path) for pattern in self.compiled_patterns)
