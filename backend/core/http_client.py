import logging
from typing import Any, Dict, Optional, Union

import aiohttp
import json_tricks

from backend.core.utils import utilities


# Используем логгер, настроенный для Graylog
request_logger = logging.getLogger("request")


class LoggingClientSession:
    """
    Кастомный HTTP-клиент с логированием всех исходящих запросов и ответов.

    Атрибуты:
        session (aiohttp.ClientSession): Сессия для выполнения HTTP-запросов.
    """

    def __init__(self):
        """Инициализирует клиентскую сессию."""
        self.session = None

    async def __aenter__(self):
        """
        Инициализация асинхронного контекстного менеджера.

        Returns:
            LoggingClientSession: Экземпляр класса.
        """
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """
        Завершение асинхронного контекстного менеджера.

        Args:
            exc_type: Тип исключения (если есть).
            exc_val: Значение исключения (если есть).
            exc_tb: Трассировка стека (если есть).
        """
        await self.session.close()

    async def request(self, method: str, url: str, **kwargs) -> aiohttp.ClientResponse:
        """
        Отправляет HTTP-запрос и логирует его.

        Args:
            method (str): HTTP-метод (GET, POST и т.д.).
            url (str): URL запроса.
            **kwargs: Дополнительные аргументы для aiohttp.ClientSession.request.

        Returns:
            aiohttp.ClientResponse: Ответ от сервера.

        Raises:
            ValueError: Если данные не могут быть сериализованы в JSON.
            aiohttp.ClientError: Если возникает ошибка при выполнении запроса.
        """
        # Логируем запрос
        request_logger.info(f"Исходящий запрос: {method} {url}")

        # Логируем заголовки
        if kwargs.get("headers"):
            request_logger.info(f"Заголовки запроса: {kwargs['headers']}")

        # Логируем параметры запроса
        if kwargs.get("params"):
            request_logger.info(f"Параметры запроса: {kwargs['params']}")

        # Логируем тело запроса
        if kwargs.get("json"):
            try:
                request_logger.info(f"Тело запроса (JSON): {kwargs['json']}")
            except Exception as e:
                request_logger.error(f"Ошибка при логировании тела запроса (JSON): {e}")
                raise ValueError("Невозможно сериализовать тело запроса в JSON")
        elif kwargs.get("data"):
            request_logger.info(f"Тело запроса (data): {kwargs['data']}")

        try:
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
        except aiohttp.ClientError as e:
            request_logger.error(f"Ошибка при выполнении запроса: {e}")
            raise

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


async def make_request(
    method: str,
    url: str,
    headers: Optional[Dict[str, str]] = None,
    json: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    data: Optional[Union[Dict[str, Any], str, bytes]] = None,
    auth_token: Optional[str] = None,
    response_type: str = "json",
) -> Dict[str, Any]:
    """
    Универсальный метод для выполнения HTTP-запросов.

    Args:
        method (str): HTTP-метод (GET, POST, PUT, DELETE и т.д.).
        url (str): Полный URL для запроса.
        headers (Optional[Dict[str, str]]): Заголовки запроса.
        json (Optional[Dict[str, Any]]): Тело запроса в формате JSON.
        params (Optional[Dict[str, Any]]): Параметры запроса (query parameters).
        data (Optional[Union[Dict[str, Any], str, bytes]]): Тело запроса для form-data или raw данных.
        auth_token (Optional[str]): Токен авторизации (добавляется в заголовки).
        response_type (str): Тип ожидаемого ответа ("json", "text", "bytes"). По умолчанию "json".

    Returns:
        Dict[str, Any]: Словарь, содержащий статус код и данные ответа.
            Пример: {"status_code": 200, "data": {...}}.

    Raises:
        ValueError: Если указан неподдерживаемый response_type.
        aiohttp.ClientError: Если возникает ошибка при выполнении запроса.
    """
    # Формируем заголовки
    default_headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    if auth_token:
        default_headers["Authorization"] = auth_token
    if headers:
        default_headers.update(headers)

    try:
        async with LoggingClientSession() as session:
            # Сериализуем JSON с помощью json_tricks
            json_data = (
                json_tricks.dumps(json, extra_obj_encoders=[utilities.custom_encoder])
                if json
                else None
            )

            # Отправляем запрос
            response = await session.request(
                method,
                url,
                headers=default_headers,
                data=json_data,  # Используем data вместо json
                params=params,
            )

            # Обрабатываем ответ
            if response_type == "json":
                response_data = await response.json()
            elif response_type == "text":
                response_data = await response.text()
            elif response_type == "bytes":
                response_data = await response.read()
            else:
                raise ValueError(f"Unsupported response_type: {response_type}")

            return {
                "status_code": response.status,
                "data": response_data,
            }
    except aiohttp.ClientError as e:
        request_logger.error(f"Ошибка при выполнении запроса: {e}")
        return {
            "status_code": 500,
            "data": None,
        }
