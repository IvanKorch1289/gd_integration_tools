from fastapi import Request, Response

from gd_advanced_tools.core.logging_config import app_logger


class AsyncListIterator:
    """
    Класс, реализующий асинхронный итератор над списком байтов.
    """

    def __init__(self, chunks):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            result = self.chunks[self.index]
            self.index += 1
            return result
        except IndexError:
            raise StopAsyncIteration


class LoggingMiddleware:
    @staticmethod
    async def intercept_response(response: Response) -> bytes:
        """Собирает и возвращает тело ответа."""
        response_body_chunks = []
        async for chunk in response.body_iterator:
            response_body_chunks.append(chunk)
        return b"".join(response_body_chunks)

    @classmethod
    async def capture_and_return_response(cls, response: Response):
        """Захватывает тело ответа, логирует его и возвращает оригинальный поток данных."""
        original_body = await cls.intercept_response(response)

        # Создаем асинхронный итератор над телом ответа
        response.body_iterator = AsyncListIterator([original_body])
        return original_body

    async def __call__(self, request: Request, call_next):
        app_logger.info(f"Запрос: {request.method} {request.url}")

        if request.method == "POST":
            request_body = await request.body()
            app_logger.info(f"Тело запроса: {request_body.decode('utf-8')}")

        response = await call_next(request)

        captured_body = await self.capture_and_return_response(response)
        if 200 <= response.status_code < 300:
            app_logger.info(f"Тело ответа: {captured_body.decode('utf-8')}")

        app_logger.info(f"Ответ: {response.status_code}")

        return response
