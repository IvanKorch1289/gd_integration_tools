from fastapi import HTTPException, Request, Response
from fastapi.responses import JSONResponse

from backend.core.logging_config import app_logger
from backend.core.settings import settings


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

        response.body_iterator = AsyncListIterator([original_body])
        return original_body

    async def __call__(self, request: Request, call_next):
        app_logger.info(f"Запрос: {request.method} {request.url}")

        if request.method == "POST":
            request_body = await request.body()
            app_logger.info(f"Тело запроса: {request_body.decode('utf-8')}")

        response = await call_next(request)

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
            app_logger.debug("Тело ответа не было декодировано.")

        app_logger.info(f"Ответ: {response.status_code}")

        return response


class APIKeyMiddleware:
    async def __call__(self, request: Request, call_next) -> Response:
        if request.url.path in ["/docs", "/openapi.json"]:
            return await call_next(request)
        try:
            api_key = request.headers["X-Api-Key"]
            await self.verify_api_key(api_key)
        except KeyError:
            return JSONResponse({"detail": "Missing X-Api-Key header"}, status_code=400)
        except HTTPException as e:
            return JSONResponse({"detail": e.detail}, status_code=e.status_code)

        response = await call_next(request)
        return response

    @staticmethod
    async def verify_api_key(api_key: str):
        if api_key != settings.app_api_key:
            raise HTTPException(status_code=401, detail="Invalid API Key")
