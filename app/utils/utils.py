from base64 import b64decode, b64encode
from datetime import datetime
from typing import Any, Dict, Optional, Type
from uuid import UUID

from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.utils.decorators.singleton import singleton
from app.utils.logging_service import app_logger


__all__ = (
    "utilities",
    "AsyncChunkIterator",
)


@singleton
class Utilities:
    """Класс утилит для общих операций и интеграции с внешними сервисами.

    Содержит методы для преобразования данных, работы с протоколами,
    выполнения асинхронных задач и форматирования данных.
    """

    logger = app_logger

    def transfer_model_to_schema(
        self,
        instance: Any,
        schema: Type[BaseModel],
        from_attributes: bool = False,
    ) -> BaseModel:
        """Преобразует экземпляр модели в схему Pydantic.

        Аргументы:
            instance: Экземпляр модели для преобразования
            schema: Целевой класс схемы Pydantic
            from_attributes: Флаг режима ORM-преобразования

        Возвращает:
            BaseModel: Инициализированный экземпляр схемы

        Исключения:
            ValueError: При ошибке преобразования
        """
        try:
            return schema.model_validate(
                instance, from_attributes=from_attributes
            )
        except Exception as exc:
            self.logger.error(
                f"Ошибка преобразования модели в схему: {str(exc)}",
                exc_info=True,
            )
            raise ValueError("Ошибка преобразования модели в схему") from exc

    async def encode_base64(self, data: Any) -> Any:
        """Кодирует данные в Base64 с поддержкой сложных структур.

        Аргументы:
            data: Входные данные (строка, словарь, список, кортеж и т.д.)

        Возвращает:
            Данные с преобразованными строками в Base64-представление
        """
        if isinstance(data, (str, bytes)):
            # Кодируем строку или байты в Base64
            if isinstance(data, str):
                data = data.encode("utf-8")
            return b64encode(data).decode("ascii")
        elif isinstance(data, (dict, list, tuple)):
            if isinstance(data, dict):
                return {
                    key: await self.encode_base64(value)
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.encode_base64(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не строка и не коллекция
            return data

    async def decode_base64(self, data: Any) -> Any:
        """Декодирует Base64-данные с поддержкой сложных структур.

        Аргументы:
            data: Закодированные данные (строка, словарь, список и т.д.)

        Возвращает:
            Данные с преобразованными Base64-строками в оригинальный формат
        """
        if isinstance(data, str):
            try:
                # Декодируем Base64 строку в байты
                decoded_bytes = b64decode(data)
                # Пытаемся декодировать байты в строку UTF-8
                return decoded_bytes.decode("utf-8")
            except (UnicodeDecodeError, ValueError):
                # Если декодирование в строку не удалось, возвращаем байты
                return decoded_bytes
        elif isinstance(data, (dict, list, tuple)):
            # Рекурсивно обрабатываем вложенные структуры
            if isinstance(data, dict):
                return {
                    key: await self.decode_base64(value)
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.decode_base64(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не строка и не коллекция
            return data

    async def decode_bytes(self, data: Any) -> Any:
        """Декодирует байтовые данные из Redis в читаемый формат.

        Аргументы:
            data: Входные данные из Redis (байты или сложная структура)

        Возвращает:
            Данные с преобразованными байтами в строки UTF-8
        """
        if isinstance(data, bytes):
            # Декодируем байты в строку
            data = data.decode("utf-8")
        if isinstance(data, (dict, list, tuple)):
            # Рекурсивно обрабатываем вложенные структуры
            if isinstance(data, dict):
                return {
                    await self.decode_bytes(key): await self.decode_bytes(
                        value
                    )
                    for key, value in data.items()
                }
            elif isinstance(data, (list, tuple)):
                return [await self.decode_bytes(item) for item in data]
        else:
            # Возвращаем данные как есть, если это не байты и не коллекция
            return data

    def ensure_url_protocol(self, url: str) -> str:
        """Добавляет протокол к URL при его отсутствии.

        Аргументы:
            url: Исходный URL

        Возвращает:
            URL с корректным протоколом (http:// или https://)
        """
        if not url.startswith(("http://", "https://")):
            return f"http://{url}"
        return url

    def generate_link_page(self, url: str, description: str) -> HTMLResponse:
        """Генерирует HTML-страницу с кликабельной ссылкой.

        Аргументы:
            url: Целевой URL
            description: Текст описания ссылки

        Возвращает:
            HTMLResponse: Сгенерированная HTML-страница
        """
        return HTMLResponse(
            f"""
            <html>
                <body>
                    <p>{description} link: <a href="{url}" target="_blank">{url}</a></p>
                </body>
            </html>
            """
        )

    def convert_numpy_types(self, value: Any) -> Any:
        """Конвертирует numpy-типы в стандартные Python-типы.

        Аргументы:
            value: Значение для конвертации

        Возвращает:
            Значение с преобразованными типами (int, float, bool)
        """
        import pandas as pd

        if pd.api.types.is_integer(value):
            return int(value)
        if pd.api.types.is_float(value):
            return float(value)
        if pd.api.types.is_bool(value):
            return bool(value)
        return value

    def convert_data(self, obj):
        """Рекурсивно преобразует объекты Pydantic в словари.

        Аргументы:
            obj: Объект для преобразования (Pydantic модель, список и др.)

        Возвращает:
            Словарь или список с преобразованными данными
        """
        if isinstance(obj, BaseModel):
            return obj.model_dump()
        elif isinstance(obj, list):
            return [self.convert_data(item) for item in obj]
        else:
            return obj

    def custom_json_encoder(self, obj: Any) -> dict:
        """Кастомный JSON-кодировщик для специальных типов данных.

        Поддерживает:
        - UUID
        - datetime
        - Модели Pydantic

        Исключения:
            TypeError: Для неподдерживаемых типов
        """
        if isinstance(obj, UUID):
            return {"__uuid__": True, "value": str(obj)}
        if isinstance(obj, datetime):
            return {"__datetime__": True, "value": obj.isoformat()}
        if isinstance(obj, BaseModel):
            obj = obj.model_dump()
        raise TypeError(f"Неподдерживаемый тип: {type(obj)}")

    def custom_json_decoder(self, dct: dict) -> Any:
        """Кастомный JSON-декодер для специальных типов данных."""
        if "__uuid__" in dct:
            return UUID(dct["value"])
        if "__datetime__" in dct:
            return datetime.fromisoformat(dct["value"])
        return dct

    async def connect_to_websocket_for_settings(
        self,
    ) -> Optional[Dict[str, Any]]:
        """Устанавливает соединение с WebSocket для получения настроек.

        Возвращает:
            Optional[Dict[str, Any]]: Словарь с настройками или None при ошибке
        """
        import asyncio

        import json_tricks
        import websockets

        from app.config.settings import settings

        # Формируем URI для подключения
        uri = f"ws://{settings.app.base_url}/ws/settings"

        try:
            async with websockets.connect(
                uri,
                ping_timeout=settings.app.socket_ping_timeout,
                close_timeout=settings.app.socket_close_timeout,
            ) as websocket:
                # Получаем сообщение от сервера
                message = await asyncio.wait_for(
                    websocket.recv(), timeout=settings.app.socket_close_timeout
                )

                self.logger.info("Успешное получение настроек через WebSocket")

                return json_tricks.loads(message)
        except Exception as exc:
            self.logger.error(f"Ошибка подключения: {str(exc)}", exc_info=True)
        return None

    async def safe_get(
        self, data: dict, keys: str, default: Any = None
    ) -> Any:
        """
        Безопасно извлекает значение из вложенного словаря.

        Args:
            data (dict): Исходный словарь.
            keys (str): Ключи для доступа к значению, разделенные точками (например, "key1.key2.key3").
            default (Any): Значение по умолчанию, если ключ не найден.

        Returns:
            Any: Найденное значение или значение по умолчанию.
        """
        current = data
        keys = keys.split(".")
        for key in keys:
            if isinstance(current, dict):
                current = current.get(key, {})
            else:
                return default
        return current if current is not None else default


class AsyncChunkIterator:
    """Асинхронный итератор для последовательного чтения байтовых чанков."""

    def __init__(self, chunks: list[bytes]):
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


utilities = Utilities()
