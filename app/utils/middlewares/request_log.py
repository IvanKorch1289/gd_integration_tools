from fastapi import Request, Response
from starlette.middleware.base import (
    BaseHTTPMiddleware,
    RequestResponseEndpoint,
)
from starlette.types import ASGIApp

from app.utils.utils import AsyncChunkIterator


__all__ = ("InnerRequestLoggingMiddleware",)


class InnerRequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Middleware для логирования входящих запросов и исходящих ответов.

    Логирует метод запроса, URL, тело запроса (если включено), статус ответа,
    время обработки и тело ответа (если включено). Поддерживает обработку сжатых данных (gzip).
    """

    def __init__(self, app: ASGIApp):
        """
        Инициализация middleware.

        :param app: ASGI-приложение, к которому применяется middleware.
        """
        from app.config.settings import settings
        from app.utils.logging_service import app_logger

        super().__init__(app)
        self.log_body = (
            settings.logging.log_requests
        )  # Флаг логирования тела запроса/ответа
        self.max_body_size = (
            settings.logging.max_body_log_size
        )  # Максимальный размер тела для логирования
        self.logger = app_logger  # Логгер

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        """
        Обработка запроса и ответа с логированием.

        :param request: Входящий HTTP-запрос.
        :param call_next: Функция для вызова следующего middleware или конечного обработчика.
        :return: HTTP-ответ.
        :raises Exception: Если возникает ошибка при обработке запроса.
        """
        from time import time

        self.logger.info(f"Запрос: {request.method} {request.url}")

        start_time = time()

        # Логирование тела запроса (если включено и это POST-запрос)
        if self.log_body and request.method == "POST":
            content_type = request.headers.get("Content-Type", "").lower()
            if "multipart/form-data" not in content_type:
                await self._get_request_body(request)

        try:
            response = await call_next(request)
        except Exception as exc:
            self.logger.error(
                f"Ошибка обработки запроса: {str(exc)}", exc_info=True
            )
            raise

        # Логирование тела ответа (если включено)
        if self.log_body:
            await self._log_response_body(response)

        # Логирование времени обработки запроса
        process_time = (time() - start_time) * 1000
        self.logger.info(
            f"Ответ: {response.status_code} | {request.method} {request.url.path} "
            f"обработан за {process_time:.2f} мс"
        )

        return response

    async def _get_request_body(self, request: Request) -> bytes:
        """
        Получение и логирование тела запроса с ограничением по размеру.

        :param request: Входящий HTTP-запрос.
        :return: Тело запроса в виде байтов.
        :raises UnicodeDecodeError: Если тело запроса содержит бинарные данные и не может быть декодировано.
        """
        try:
            body = await request.body()
            if len(body) > self.max_body_size:
                return "<тело запроса слишком велико для логирования>".encode(
                    "utf-8"
                )

            self.logger.debug(f"Тело запроса: {body.decode('utf-8')}")
            return body
        except UnicodeDecodeError:
            self.logger.warning(
                "Тело запроса содержит бинарные данные, логирование пропущено"
            )
            return b""

    async def _log_response_body(self, response: Response) -> None:
        """
        Логирование тела ответа с ограничением по размеру.

        :param response: HTTP-ответ.
        :raises Exception: Если возникает ошибка при декодировании или распаковке данных.
        """
        from gzip import GzipFile
        from io import BytesIO

        content_type = response.headers.get("Content-Type", "").lower()
        content_encoding = response.headers.get("Content-Encoding", "").lower()

        # Получение тела ответа
        body = await self._capture_response_body(response)

        # Обработка сжатых данных (gzip)
        if content_encoding == "gzip":
            try:
                with GzipFile(fileobj=BytesIO(body)) as gzip_file:
                    body = gzip_file.read()
            except Exception as exc:
                self.logger.error(
                    f"Ошибка распаковки gzip-ответа: {str(exc)}",
                    exc_info=True,
                )
                return

        # Логирование текстовых или JSON-данных
        if "text" in content_type or "json" in content_type:
            try:
                decoded_body = body.decode("utf-8")
                if len(decoded_body) > self.max_body_size:
                    self.logger.debug(
                        "Тело ответа слишком велико для логирования"
                    )
                else:
                    self.logger.debug(f"Тело ответа: {decoded_body}")
            except UnicodeDecodeError:
                self.logger.warning(
                    "Тело ответа не является валидным текстом UTF-8"
                )
            except Exception as exc:
                self.logger.error(
                    f"Ошибка декодирования тела ответа: {str(exc)}",
                    exc_info=True,
                )
        else:
            # Логирование бинарных данных (например, файлов)
            self.logger.debug(
                f"Тело ответа - бинарные данные, размер: {len(body)} байт"
            )

    @staticmethod
    async def _capture_response_body(response: Response) -> bytes:
        """
        Захват тела ответа с сохранением оригинального итератора.

        :param response: HTTP-ответ.
        :return: Тело ответа в виде байтов.
        """
        chunks = []
        async for chunk in response.body_iterator:  # type: ignore
            chunks.append(chunk)
        response.body_iterator = AsyncChunkIterator(chunks)  # type: ignore
        return b"".join(chunks)
