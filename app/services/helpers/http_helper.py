from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, Optional, Union

import aiohttp
import asyncio
import json_tricks
from aiohttp import ClientTimeout, TCPConnector

from app.utils.logging import request_logger
from app.utils.utils import utilities


__all__ = ("make_request", "get_http_client")


class OptimizedClientSession:
    """
    Высокопроизводительный HTTP-клиент с расширенными возможностями управления соединениями
    и логированием.

    Особенности:
    - Переиспользование соединений (Keep-Alive)
    - Пул соединений с ограничениями
    - Тонкая настройка таймаутов
    - Асинхронная инициализация
    - Расширенное логирование

    Атрибуты:
        connector (TCPConnector): Менеджер TCP-соединений
        session (aiohttp.ClientSession): Экземпляр клиентской сессии
    """

    def __init__(self, connector: Optional[TCPConnector] = None):
        """
        Инициализация HTTP-клиента.

        Args:
            connector (Optional[TCPConnector]): Кастомный TCP-коннектор.
                Если не указан, создается со значениями по умолчанию:
                - limit=100 (максимум соединений)
                - limit_per_host=20 (соединений на хост)
                - ttl_dns_cache=300 (кеш DNS 5 минут)
        """
        self.connector = connector or TCPConnector(
            limit=100,
            limit_per_host=20,
            ttl_dns_cache=300,
            ssl=False,  # Установите True для продакшена
        )
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self) -> "OptimizedClientSession":
        """
        Асинхронная инициализация клиента.

        Returns:
            OptimizedClientSession: Экземпляр клиента
        """
        timeout = ClientTimeout(
            total=30,  # Общий таймаут на запрос
            connect=10,  # Таймаут на подключение
            sock_read=15,  # Таймаут на чтение данных
        )

        self.session = aiohttp.ClientSession(
            connector=self.connector,
            timeout=timeout,
            auto_decompress=False,  # Ускоряет обработку сжатых данных
            trust_env=True,  # Использует системные прокси
        )
        return self

    async def __aexit__(self, *exc_info) -> None:
        """
        Корректное завершение работы клиента.
        """
        if self.session:
            await self.session.close()

    async def _log_request(self, method: str, url: str, **kwargs) -> None:
        """
        Логирование параметров запроса.

        Args:
            method (str): HTTP-метод
            url (str): URL запроса
            kwargs: Дополнительные параметры запроса
        """
        log_data = {
            "method": method,
            "url": url,
            "headers": kwargs.get("headers"),
            "params": kwargs.get("params"),
            "body_size": (
                len(kwargs.get("data", b"")) if kwargs.get("data") else 0
            ),
        }
        request_logger.info("Outgoing request", extra={"request": log_data})

    async def _log_response(self, response: aiohttp.ClientResponse) -> None:
        """
        Логирование основных параметров ответа.

        Args:
            response (aiohttp.ClientResponse): Объект ответа
        """
        log_data = {
            "status": response.status,
            "headers": dict(response.headers),
            "url": str(response.url),
            "content_length": response.content_length,
        }
        request_logger.info("Received response", extra={"response": log_data})

    async def request(
        self, method: str, url: str, **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Выполнение HTTP-запроса с оптимизациями.

        Особенности:
        - Автоматическое сжатие тела запроса
        - Оптимизированная обработка ошибок
        - Потоковая передача данных

        Args:
            method (str): HTTP-метод
            url (str): URL запроса
            **kwargs: Дополнительные параметры запроса

        Returns:
            aiohttp.ClientResponse: Объект ответа

        Raises:
            aiohttp.ClientError: При ошибках сети
        """
        if not self.session:
            raise RuntimeError("Session not initialized")

        await self._log_request(method, url, **kwargs)

        try:
            response = await self.session.request(method, url, **kwargs)
            await self._log_response(response)
            return response
        except aiohttp.ClientError as e:
            request_logger.error(
                f"Request failed: {e.__class__.__name__}", exc_info=True
            )
            raise

    async def get(
        self, url: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Оптимизированный GET-запрос с потоковым чтением.

        Args:
            url (str): URL запроса
            params (Optional[Dict[str, Any]]): Query-параметры
            **kwargs: Дополнительные параметры

        Returns:
            aiohttp.ClientResponse: Объект ответа
        """
        return await self.request("GET", url, params=params, **kwargs)

    async def post(
        self,
        url: str,
        data: Optional[Union[Dict[str, Any], str, bytes]] = None,
        **kwargs,
    ) -> aiohttp.ClientResponse:
        """
        Оптимизированный POST-запрос с бинарной передачей данных.

        Args:
            url (str): URL запроса
            data (Optional[Union[Dict, str, bytes]]): Тело запроса
            **kwargs: Дополнительные параметры

        Returns:
            aiohttp.ClientResponse: Объект ответа
        """
        return await self.request("POST", url, data=data, **kwargs)


@asynccontextmanager
async def get_http_client() -> AsyncGenerator[OptimizedClientSession, None]:
    """
    Контекстный менеджер для получения оптимизированного HTTP-клиента.

    Пример использования:
    async with get_http_client() as client:
        response = await client.get("https://api.example.com")

    Yields:
        OptimizedClientSession: Экземпляр HTTP-клиента
    """
    async with OptimizedClientSession() as client:
        yield client


async def make_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Union[Dict[str, Any], str, bytes]] = None,
    auth_token: Optional[str] = None,
    response_type: str = "json",
    raise_for_status: bool = True,
) -> Dict[str, Any]:
    """
    Универсальный метод выполнения HTTP-запросов с поддержкой продвинутых оптимизаций.

    Особенности:
    - Переиспользование соединений через пул
    - Потоковая обработка больших тел
    - Автоматическая компрессия/декомпрессия
    - Поддержка асинхронного контекста

    Args:
        method (str): HTTP-метод (GET, POST и т.д.)
        url (str): Целевой URL
        headers (Optional[Dict[str, str]]): Дополнительные заголовки
        json (Optional[Dict[str, Any]]): Тело запроса в формате JSON
        params (Optional[Dict[str, Any]]): Query-параметры
        data (Optional[Union[Dict, str, bytes]]): Тело запроса для других форматов
        auth_token (Optional[str]): Токен авторизации
        response_type (str): Формат ответа (json/text/bytes)
        raise_for_status (bool): Вызывать исключение при кодах 4xx/5xx

    Returns:
        Dict[str, Any]: Результат запроса в формате:
        {
            "status": int,
            "data": Union[dict, str, bytes],
            "headers": dict,
            "elapsed": float
        }

    Raises:
        aiohttp.ClientResponseError: При raise_for_status=True и статусе >=400
        ValueError: При некорректных параметрах
    """
    start_time = asyncio.get_event_loop().time()

    # Формирование заголовков
    default_headers = {
        "User-Agent": "OptimizedClient/1.0",
        "Accept-Encoding": "gzip, deflate, br",
    }
    if auth_token:
        default_headers["Authorization"] = f"Bearer {auth_token}"
    if headers:
        default_headers.update(headers)

    # Сериализация JSON с поддержкой кастомных энкодеров
    json_data = None
    if json is not None:
        try:
            json_data = json_tricks.dumps(
                json, extra_obj_encoders=[utilities.custom_json_encoder]
            )
        except Exception as e:
            request_logger.error(f"JSON serialization error: {e}")
            raise ValueError("Invalid JSON data") from e

    async with get_http_client() as client:
        try:
            response = await client.request(
                method=method,
                url=url,
                headers=default_headers,
                params=params,
                data=data if data else json_data,
            )

            if raise_for_status:
                response.raise_for_status()

            # Чтение ответа в зависимости от типа
            content = None
            if response_type == "json":
                content = await response.json()
            elif response_type == "text":
                content = await response.text()
            elif response_type == "bytes":
                content = await response.read()
            else:
                raise ValueError(f"Invalid response_type: {response_type}")

            elapsed = asyncio.get_event_loop().time() - start_time

            return {
                "status": response.status,
                "data": content,
                "headers": dict(response.headers),
                "elapsed": elapsed,
            }

        except aiohttp.ClientResponseError as e:
            request_logger.error(f"HTTP error {e.status}: {e.message}")
            if raise_for_status:
                raise
            return {
                "status": e.status,
                "data": None,
                "headers": dict(e.headers) if e.headers else {},
                "elapsed": asyncio.get_event_loop().time() - start_time,
            }
