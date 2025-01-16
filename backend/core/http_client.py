import logging
from typing import Any, Dict, Optional

import aiohttp


# Используем логгер, настроенный для Graylog
request_logger = logging.getLogger("request")


class LoggingClientSession:
    """
    Кастомный HTTP-клиент с логированием всех исходящих запросов и ответов.
    """

    def __init__(self):
        self.session = aiohttp.ClientSession()

    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """
        Отправляет HTTP-запрос и логирует его.

        Args:
            method (str): HTTP-метод (GET, POST и т.д.).
            url (str): URL запроса.
            **kwargs: Дополнительные аргументы для aiohttp.ClientSession.request.

        Returns:
            aiohttp.ClientResponse: Ответ от сервера.
        """
        # Логируем запрос
        request_logger.info(f"Исходящий запрос: {method} {url}")
        if kwargs.get("params"):
            request_logger.info(f"Параметры запроса: {kwargs['params']}")
        if kwargs.get("json"):
            request_logger.info(f"Тело запроса (JSON): {kwargs['json']}")
        elif kwargs.get("data"):
            request_logger.info(f"Тело запроса (data): {kwargs['data']}")

        # Отправляем запрос
        response = await self.session.request(method, url, **kwargs)

        # Логируем ответ
        request_logger.info(f"Ответ от {url}: статус {response.status}")
        try:
            response_body = await response.text()
            request_logger.info(f"Тело ответа: {response_body}")
        except Exception as e:
            request_logger.warning(f"Не удалось прочитать тело ответа: {e}")

        return response

    async def get(
        self, url: str, params: Optional[Dict[str, Any]] = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Отправляет GET-запрос и логирует его.

        Args:
            url (str): URL запроса.
            params (Optional[Dict[str, Any]]): Параметры запроса.
            **kwargs: Дополнительные аргументы для aiohttp.ClientSession.get.

        Returns:
            aiohttp.ClientResponse: Ответ от сервера.
        """
        return await self.request("GET", url, params=params, **kwargs)

    async def post(
        self, url: str, data: Optional[Dict[str, Any]] = None, **kwargs
    ) -> aiohttp.ClientResponse:
        """
        Отправляет POST-запрос и логирует его.

        Args:
            url (str): URL запроса.
            data (Optional[Dict[str, Any]]): Данные для отправки.
            **kwargs: Дополнительные аргументы для aiohttp.ClientSession.post.

        Returns:
            aiohttp.ClientResponse: Ответ от сервера.
        """
        return await self.request("POST", url, data=data, **kwargs)

    async def close(self):
        """
        Закрывает сессию.
        """
        await self.session.close()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
