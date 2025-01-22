import re
from typing import Callable

import asyncio
import time
from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from backend.core.logging_config import app_logger
from backend.core.settings import settings


class AsyncListIterator:
    """
    Асинхронный итератор для последовательного обхода списка байтовых чанков.

    Attributes:
        chunks (list): Список байтовых чанков.
        index (int): Текущий индекс в списке чанков.
    """

    def __init__(self, chunks):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        """
        Возвращает следующий чанк из списка.

        Raises:
            StopAsyncIteration: Если достигнут конец списка.
        """
        try:
            result = self.chunks[self.index]
            self.index += 1
            return result
        except IndexError:
            raise StopAsyncIteration


class InnerRequestLoggingMiddleware:
    """
    Middleware для логирования входящих запросов и исходящих ответов.

    Логирует метод, URL, тело запроса (для POST), тело ответа и время обработки.
    Также перехватывает и логирует исключения, возникающие в процессе обработки запроса.
    """

    async def __call__(self, request: Request, call_next: Callable):
        """
        Обрабатывает входящий запрос и логирует информацию о нем.

        Args:
            request (Request): Входящий HTTP-запрос.
            call_next (Callable): Функция для вызова следующего middleware или обработчика запроса.

        Returns:
            Response: HTTP-ответ.
        """
        app_logger.info(f"Запрос: {request.method} {request.url}")

        start_time = time.time()

        # Проверяем, является ли запрос бинарным (например, загрузка файла)
        content_type = request.headers.get("Content-Type", "").lower()

        if request.method == "POST" and "multipart/form-data" not in content_type:
            # Логируем тело запроса только для небинарных данных
            request_body = await request.body()
            try:
                app_logger.info(f"Тело запроса: {request_body.decode('utf-8')}")
            except UnicodeDecodeError:
                app_logger.warning(
                    "Тело запроса содержит бинарные данные и не может быть декодировано."
                )

        try:
            response = await call_next(request)
        except Exception as exc:
            # Логируем исключение
            app_logger.error(f"Ошибка при обработке запроса: {exc}", exc_info=True)
            # Передаем исключение дальше для обработки глобальным обработчиком
            raise

        # Логируем тело ответа только для текстовых или JSON-ответов
        captured_body = await self.capture_and_return_response(response)
        content_type = response.headers.get("Content-Type", "").lower()
        if "text" in content_type or "json" in content_type:
            try:
                app_logger.info(f"Тело ответа: {captured_body.decode('utf-8')}")
            except UnicodeDecodeError as e:
                app_logger.warning(
                    f"Произошла ошибка при декодировании тела ответа: {e}"
                )
        else:
            app_logger.debug("Тело ответа не было декодировано (бинарные данные).")

        process_time = (time.time() - start_time) * 1000

        app_logger.info(
            f"Ответ: {response.status_code}, {request.method} {request.url.path}: {process_time:.2f} ms"
        )

        return response

    @staticmethod
    async def intercept_response(response: Response) -> bytes:
        """
        Собирает и возвращает тело ответа.

        Args:
            response (Response): HTTP-ответ.

        Returns:
            bytes: Тело ответа в виде байтов.
        """
        response_body_chunks = []
        async for chunk in response.body_iterator:
            response_body_chunks.append(chunk)
        return b"".join(response_body_chunks)

    @classmethod
    async def capture_and_return_response(cls, response: Response):
        """
        Захватывает тело ответа, логирует его и возвращает оригинальный поток данных.

        Args:
            response (Response): HTTP-ответ.

        Returns:
            bytes: Тело ответа в виде байтов.
        """
        original_body = await cls.intercept_response(response)
        response.body_iterator = AsyncListIterator([original_body])
        return original_body


class APIKeyMiddleware:
    """
    Middleware для проверки API-ключа в заголовке запроса.

    Если маршрут не требует API-ключа, запрос пропускается без проверки.
    """

    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """
        Проверяет наличие и валидность API-ключа в заголовке запроса.

        Args:
            request (Request): Входящий HTTP-запрос.
            call_next (Callable): Функция для вызова следующего middleware или обработчика запроса.

        Returns:
            Response: HTTP-ответ.
        """
        # Проверяем, требуется ли API-ключ для текущего пути
        if self._is_path_excluded(request.url.path):
            return await call_next(request)

        # Проверяем наличие и валидность API-ключа
        try:
            api_key = request.headers["X-Api-Key"]
            await self.verify_api_key(api_key)
        except KeyError:
            raise  # Исключение будет обработано глобальным обработчиком
        except HTTPException:
            raise  # Исключение будет обработано глобальным обработчиком

        # Продолжаем обработку запроса
        response = await call_next(request)
        return response

    @staticmethod
    async def verify_api_key(api_key: str):
        """
        Проверяет валидность API-ключа.

        Args:
            api_key (str): API-ключ из заголовка запроса.

        Raises:
            HTTPException: Если API-ключ невалиден.
        """
        if api_key != settings.app_api_key:
            raise HTTPException(status_code=401, detail="Invalid API Key")

    def _is_path_excluded(self, path: str) -> bool:
        """
        Проверяет, исключен ли путь из проверки API-ключа.

        Args:
            path (str): Путь запроса.

        Returns:
            bool: True, если путь исключен, иначе False.
        """
        # Проверяем, соответствует ли путь любому из исключенных маршрутов
        for excluded_path in settings.app_routes_without_api_key:
            pattern = excluded_path.replace("*", ".*")
            # Добавляем начало и конец строки для точного совпадения
            pattern = f"^{pattern}$"
            if re.match(pattern, path):
                return True
        return False


class TimeoutMiddleware:
    """
    Middleware для установки таймаута на обработку запроса.

    Если запрос обрабатывается дольше указанного времени, возвращается ошибка 408.
    """

    @classmethod
    async def __call__(cls, request: Request, call_next: Callable):
        """
        Устанавливает таймаут на обработку запроса.

        Args:
            request (Request): Входящий HTTP-запрос.
            call_next (Callable): Функция для вызова следующего middleware или обработчика запроса.

        Returns:
            Response: HTTP-ответ.
        """
        try:
            response = await asyncio.wait_for(
                call_next(request), timeout=settings.app_request_timeout
            )
        except asyncio.TimeoutError:
            return JSONResponse({"detail": "Request timed out"}, status_code=408)

        return response
