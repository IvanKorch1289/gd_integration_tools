import uuid
from datetime import datetime
from typing import Any, Type

import asyncio
import json_tricks
import pandas as pd
# import pyclamd
from fastapi import Response
from fastapi.responses import HTMLResponse

from app.schemas.base import BaseSchema
from app.utils.decorators.singleton import singleton


__all__ = ("utilities",)

# cd = pyclamd.ClamdNetworkSocket(host='127.0.0.1', port=3310)


@singleton
class Utilities:
    """Класс вспомогательных функций для работы с внешними сервисами и утилитами.

    Предоставляет методы для проверки состояния сервисов (база данных, Redis, S3 и т.д.),
    а также для выполнения задач, таких как отправка электронной почты.
    """

    async def transfer_model_to_schema(
        self,
        instance: Any,
        schema: Type[BaseSchema],
        from_attributes: bool = False,
    ) -> BaseSchema:
        """Преобразует объект (модель или версию) в схему Pydantic.

        Args:
            instance (Any): Объект модели или версии.
            schema (Type[BaseModel]): Класс схемы Pydantic.
            is_versioned (bool): Флаг, указывающий, является ли объект версией.

        Returns:
            BaseModel: Экземпляр схемы Pydantic.

        Raises:
            ValueError: Если объект не может быть преобразован в схему.
        """
        try:
            return schema.model_validate(instance, from_attributes=from_attributes)
        except Exception as exc:
            raise ValueError(
                f"Ошибка при преобразовании модели в схему: {exc}"
            ) from exc

    async def get_response_type_body(self, response: Response):
        """Извлекает и преобразует тело ответа в формат JSON.

        Args:
            response (Response): Ответ от сервера.

        Returns:
            Any: Тело ответа в формате JSON.
        """
        check_services_body = response.body.decode("utf-8")
        return json_tricks.loads(check_services_body)

    async def ensure_protocol(self, url: str) -> str:
        """Добавляет протокол (http://) к URL, если он отсутствует.

        Args:
            url (str): URL-адрес.

        Returns:
            str: URL с протоколом.
        """
        if not url.startswith(("http://", "https://")):
            return f"http://{url}"
        return url

    def generate_link_page(self, url: str, description: str) -> HTMLResponse:
        """Генерирует HTML-страницу с кликабельной ссылкой.

        Args:
            url (str): URL-адрес.
            description (str): Описание ссылки.

        Returns:
            HTMLResponse: HTML-страница с ссылкой.
        """
        return HTMLResponse(
            f"""
            <html>
                <body>
                    <p>Ссылка на {description}: <a href="{url}" target="_blank">{url}</a></p>
                </body>
            </html>
            """
        )

    async def convert_numpy_types(self, value):
        """Преобразует numpy-типы (например, numpy.int64) в стандартные типы Python.

        Args:
            value: Значение, которое может быть numpy-типом.

        Returns:
            Преобразованное значение.
        """
        if pd.api.types.is_integer(value):
            return int(value)
        elif pd.api.types.is_float(value):
            return float(value)
        elif pd.api.types.is_bool(value):
            return bool(value)
        return value

    # def scan_file(file: UploadFile) -> bool:
    #     """Сканирует файл с помощью ClamAV."""
    #     try:
    #         for chunk in iter(lambda: file.file.read(8192), b""):
    #             if cd.scan_stream(chunk):
    #                 return False  # Вирус обнаружен
    #         return True  # Файл чист
    #     finally:
    #         file.file.seek(0)  # Сбрасываем позицию чтения файла

    def custom_encoder(self, obj):
        """Пользовательский кодировщик для преобразования UUID и datetime в JSON.

        Args:
            obj: Объект для кодирования.

        Returns:
            dict: Словарь с закодированными данными.

        Raises:
            TypeError: Если объект не может быть сериализован.
        """
        if isinstance(obj, uuid.UUID):
            return {"__uuid__": True, "value": str(obj)}
        elif isinstance(obj, datetime):
            return {"__datetime__": True, "value": obj.isoformat()}
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

    def custom_decoder(self, dct):
        """Пользовательский декодировщик для преобразования JSON в UUID и datetime.

        Args:
            dct: Словарь с закодированными данными.

        Returns:
            Объект UUID или datetime, если они найдены в словаре.
        """
        if "__uuid__" in dct:
            return uuid.UUID(dct["value"])
        elif "__datetime__" in dct:
            return datetime.fromisoformat(dct["value"])
        return dct

    def run_async_task(self, async_task: Any) -> Any:
        """
        Универсальный запуск асинхронных задач в синхронном контексте.

        Args:
            async_task: Корутина или асинхронная функция

        Returns:
            Сериализованный результат выполнения задачи
        """
        loop = None
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            result = loop.run_until_complete(async_task)
            return json_tricks.dumps(result).encode()
        finally:
            if loop and loop.is_closed():
                loop.close()


utilities = Utilities()
