import json
import sys
import traceback
import uuid
from datetime import datetime
from typing import Any, Dict, Type, TypeVar

import asyncio
import json_tricks
import pandas as pd
# import pyclamd
from fastapi import HTTPException, Response, status
from fastapi.responses import HTMLResponse

from app.config.settings import settings
from app.schemas import BaseSchema


__all__ = (
    "singleton",
    "utilities",
)


T = TypeVar("T")
ParamsType = Dict[str, Any]

cache_expire_seconds = settings.redis.redis_cache_expire_seconds

# cd = pyclamd.ClamdNetworkSocket(host='127.0.0.1', port=3310)


def singleton(cls):
    """Декоратор для создания Singleton-класса.

    Args:
        cls: Класс, который нужно сделать Singleton.

    Returns:
        Функция, которая возвращает единственный экземпляр класса.
    """
    instances = {}

    def get_instance(*args, **kwargs):
        if cls not in instances:
            instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance


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

    async def health_check_scheduler(self) -> bool:
        """Проверяет подключение к планировщику задач.

        Returns:
            bool: True, если подключение успешно.

        Raises:
            HTTPException: Если подключение к планировщику не удалось.
        """
        try:
            from app.config.scheluler.scheduler import (  # Ленивый импорт
                scheduler_manager,
            )

            result = await scheduler_manager.check_status()
            if not result:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Scheduler not connected",
                )
            return True
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Scheduler not connected: {str(exc)}",
            )

    async def health_check_all_services(self):
        """Проверяет состояние всех сервисов (база данных, Redis, S3, Graylog, SMTP, Celery, планировщик задач).

        Returns:
            Response: JSON-ответ с результатами проверки всех сервисов.
        """
        db_check = await self.health_check_database()
        redis_check = await self.health_check_redis()
        s3_check = await self.health_check_s3()
        graylog_check = await self.health_check_graylog()
        smtp_check = await self.health_check_smtp()
        celery_check = await self.health_check_celery()
        celery_queues_check = await self.health_check_celery_queues()
        scheduler_check = await self.health_check_scheduler()

        response_data = {
            "db": db_check,
            "redis": redis_check,
            "s3": s3_check,
            "graylog": graylog_check,
            "smtp": smtp_check,
            "celery": celery_check,
            "celery_queue": celery_queues_check,
            "scheduler": scheduler_check,
        }

        if all(response_data.values()):
            status_code = 200
            message = "All systems are operational."
            is_all_services_active = True
        else:
            status_code = 500
            message = "One or more components are not functioning properly."
            is_all_services_active = False

        response_body = {
            "message": message,
            "is_all_services_active": is_all_services_active,
            "details": response_data,
        }

        return Response(
            content=json.dumps(response_body),
            media_type="application/json",
            status_code=status_code,
        )

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

    def run_async_task(async_task: Any) -> Any:
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
