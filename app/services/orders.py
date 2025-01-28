import json
from typing import Any, Dict, List, Optional

from fastapi import Depends, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.core import (
    Event,
    S3Service,
    caching_decorator,
    event_bus,
    s3_bucket_service_factory,
)
from app.core.dependencies import (
    create_zip_streaming_response,
    get_base64_file,
    get_streaming_response,
)
from app.core.settings import settings
from app.db import OrderRepository, get_order_repo
from app.db.repositories import FileRepository, get_file_repo
from app.schemas import BaseSchema, OrderFilter, OrderSchemaIn, OrderSchemaOut
from app.services.base import BaseService
from app.services.skb import APISKBService, get_skb_service
from app.utils import ResponseTypeChoices, utilities


__all__ = (
    "OrderService",
    "get_order_service",
)


class OrderService(BaseService):
    """
    Сервис для работы с заказами. Обеспечивает создание, обновление, получение и обработку заказов,
    а также взаимодействие с внешними сервисами (например, СКБ-Техно) и файловым хранилищем.
    """

    def __init__(
        self,
        response_schema: BaseModel = None,
        request_schema: BaseModel = None,
        event_schema: Event = None,
        repo: OrderRepository = None,
        file_repo: FileRepository = None,
        request_service: APISKBService = None,
    ):
        """
        Инициализация сервиса заказов.

        :param response_schema: Схема для преобразования данных в ответ.
        :param request_schema: Схема для валидации входных данных.
        :param event_schema: Схема для событий.
        :param repo: Репозиторий для работы с заказами.
        :param file_repo: Репозиторий для работы с файлами.
        :param request_service: Сервис для взаимодействия с API СКБ-Техно.
        """
        super().__init__(
            repo=repo,
            response_schema=response_schema,
            request_schema=request_schema,
        )
        self.file_repo = file_repo
        self.request_service = request_service
        self.event_schema = event_schema

    async def add(self, data: Dict[str, Any]) -> Optional[BaseSchema]:
        """
        Создает новый заказ на основе переданных данных.

        :param data: Словарь с данными для создания заказа.
        :return: Созданный заказ или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при создании заказа.
        """
        try:
            # Создаем заказ через базовый метод
            order = await super().add(data=data)
            if order:
                check_services = await utilities.health_check_all_services()
                response_body = await utilities.get_response_type_body(check_services)
                if response_body.get("is_all_services_active", None):
                    event = Event(
                        event_type="order_created",
                        payload={"order_id": order.id, "email": order.email_for_answer},
                    )
                    await event_bus.emit(event)
            return order
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def add_many(
        self, data_list: List[Dict[str, Any]]
    ) -> Optional[List[BaseSchema]]:
        """
        Создает несколько заказов на основе списка данных.

        :param data_list: Список словарей с данными для создания заказов.
        :return: Список созданных заказов или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при создании заказов.
        """
        try:
            # Создаем заказы для каждого элемента в списке данных
            return [await self.get_or_add(data=data) for data in data_list]
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_or_add(self, data: Dict[str, Any]) -> Optional[BaseSchema]:
        """
        Получает заказ по параметрам или создает новый, если заказ не найден.

        :param data: Словарь с данными для поиска или создания заказа.
        :return: Найденный или созданный заказ. Возвращает None в случае ошибки.
        :raises Exception: Если произошла ошибка при поиске или создании заказа.
        """
        try:
            # Параметры для фильтрации заказов
            filter_params = {
                "pledge_cadastral_number__like": data.get("pledge_cadastral_number"),
                "is_active": True,
                "is_send_request_to_skb": False,
            }
            # Ищем заказ по параметрам
            instance = await self.get(filter=OrderFilter.model_validate(filter_params))

            # Если заказ не найден, создаем новый
            if not instance:
                instance = await self.add(data=data)
            elif isinstance(instance, list):
                instance = instance[-1]
            return instance
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def create_skb_order(self, order_id: int) -> Optional[OrderSchemaOut]:
        """
        Создает заказ в СКБ-Техно на основе существующего заказа.

        :param order_id: ID заказа.
        :return: Ответ от СКБ-Техно или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при создании заказа в СКБ-Техно.
        """
        try:
            # Получаем заказ по ID
            order: OrderSchemaOut = await self.get(key="id", value=order_id)

            # Преобразуем данные заказа, если это необходимо
            if isinstance(order, BaseSchema):
                order = order.model_dump()

            # Проверяем, активен ли заказ
            if order.get("is_active", None):
                return order
                # Формируем данные для запроса в СКБ-Техно
                data = {
                    "Id": order.get("object_uuid", None),
                    "OrderId": order.get("object_uuid", None),
                    "Number": order.get("pledge_cadastral_number", None),
                    "Priority": settings.api_skb_settings.skb_request_priority_default,
                    "RequestType": order.get("order_kind", None).get("skb_uuid", None),
                }
                return data
                # Отправляем запрос в СКБ-Техно
                result = await self.request_service.add_request(data=data)

                # Если запрос успешен, обновляем статус заказа
                if result["status_code"] == status.HTTP_200_OK:
                    await self.update(
                        key="id",
                        value=order.get("id", None),
                        data={"is_send_request_to_skb": True},
                    )
                    # Генерируем событие о успешной отправке заказа
                    event = Event(
                        event_type="order_sending_skb",
                        payload={
                            "order_id": order["id"],
                            "email": order["email_for_answer"],
                        },
                    )
                    await event_bus.emit(event)
                return result
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_order_result(
        self, order_id: int, response_type: ResponseTypeChoices
    ) -> JSONResponse:
        """
        Получает результат заказа из СКБ-Техно в указанном формате (JSON или PDF).

        :param order_id: ID заказа.
        :param response_type: Тип ответа (JSON или PDF).
        :return: JSONResponse с результатом или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении результата.
        """
        try:
            # Получаем заказ по ID
            instance = await self.repo.get(key="id", value=order_id)
            # Запрашиваем результат из СКБ-Техно
            result = await self.request_service.get_response_by_order(
                order_uuid=instance.object_uuid, response_type=response_type.value
            )

            # Обрабатываем JSON-ответ
            if isinstance(result, JSONResponse):
                body = json.loads(result.body.decode("utf-8"))
                if not body.get("hasError", "") and response_type.value == "JSON":
                    # Обновляем данные заказа в базе
                    await self.repo.update(
                        key="id",
                        value=instance.id,
                        data={
                            "errors": body.get("Message", None),
                            "response_data": body.get("Data", None),
                        },
                    )
                    return JSONResponse(
                        status_code=(
                            status.HTTP_400_BAD_REQUEST
                            if body.get("Message")
                            else status.HTTP_200_OK
                        ),
                        content={
                            "hasError": True if body.get("Message") else False,
                            "pledge_data": body.get("Data"),
                        },
                    )
            # Обрабатываем PDF-ответ
            elif response_type.value == "PDF":
                file = await self.file_repo.add(
                    data={"object_uuid": instance.object_uuid}
                )
                await self.file_repo.add_link(
                    data={"order_id": instance.id, "file_id": file.id}
                )
                return JSONResponse(
                    status_code=status.HTTP_200_OK,
                    content={"hasError": False, "message": "file upload to storage"},
                )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST, content={"hasError": True}
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_order_file_and_json_from_skb(
        self, order_id: int
    ) -> Optional[Dict[str, Any]]:
        """
        Получает файл и JSON-результат заказа из СКБ-Техно.

        :param order_id: ID заказа.
        :return: Данные заказа или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении данных.
        """
        try:
            # Получаем заказ по ID
            order = await self.get(key="id", value=order_id)
            if isinstance(order, self.response_schema):
                order = order.model_dump()
            if not isinstance(order, dict):
                raise ValueError(f"Expected a dictionary, but got {type(order)}")

            # Если заказ активен, запрашиваем результаты
            if order.get("is_active", None):
                pdf_response: JSONResponse = await self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.pdf
                )
                json_response: JSONResponse = await self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.json
                )

                # Если оба запроса успешны, обновляем статус заказа
                if (
                    json_response.status_code == status.HTTP_200_OK
                    and pdf_response.status_code == status.HTTP_200_OK
                ):
                    await self.update(
                        key="id", value=order_id, data={"is_active": False}
                    )
                    return order
                else:
                    return {
                        "hasError": True,
                        "message": "Результат еще не готов",
                    }
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_order_file_from_storage(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ) -> Optional[Any]:
        """
        Получает файл заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Потоковое содержимое файла или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении файла.
        """
        try:
            # Получаем заказ по ID
            order = await self.repo.get(key="id", value=order_id)
            # Формируем список файлов
            files_list = [str(file.object_uuid) for file in order.files]

            # Возвращаем файл или архив, если файлов несколько
            if len(files_list) == 1:
                return await get_streaming_response(files_list[0], s3_service)
            elif len(files_list) > 1:
                return await create_zip_streaming_response(files_list, s3_service)
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_order_file_from_storage_base64(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ) -> JSONResponse:
        """
        Получает файл заказа из хранилища S3 в формате base64.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: JSONResponse с файлами в формате base64 или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении файла.
        """
        try:
            # Получаем заказ по ID
            order = await self.repo.get(key="id", value=order_id)
            # Формируем список файлов в формате base64
            files_list = [
                {"file": await get_base64_file(str(file.object_uuid), s3_service)}
                for file in order.files
            ]
            return JSONResponse(
                status_code=status.HTTP_200_OK, content={"files": files_list}
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_order_file_from_storage_link(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ) -> List[Dict[str, str]]:
        """
        Получает ссылки для скачивания файлов заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Список ссылок для скачивания файлов или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении ссылок.
        """
        try:
            # Получаем заказ по ID
            order = await self.get(key="id", value=order_id)
            # Формируем список файлов
            files_list = (
                order.get("files", None)
                if isinstance(order, dict)
                else [file.model_dump() for file in order.files]
            )
            # Генерируем ссылки для скачивания
            files_links = [
                {
                    "file": await s3_service.generate_download_url(
                        str(file.get("object_uuid"))
                    )
                }
                for file in files_list
            ]
            return files_links
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def get_order_file_link_and_json_result_for_request(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ) -> Dict[str, Any]:
        """
        Получает ссылки на файлы и JSON-результат заказа.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Данные заказа, включая ссылки на файлы и JSON-результат, или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении данных.
        """
        try:
            # Получаем заказ по ID
            order = await self.get(key="id", value=order_id)
            order = order if isinstance(order, dict) else order.model_dump()
            # Формируем данные для ответа
            data = {
                "data": order.get("response_data", None),
                "errors": order.get("errors", None),
            }
            # Добавляем ссылки на файлы, если они есть
            if order.get("files", None):
                data["file_links"] = await self.get_order_file_from_storage_link(
                    order_id=order_id, s3_service=s3_service
                )
            return data
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @caching_decorator
    async def send_data_to_gd(self, order_id: int) -> None:
        """
        Отправляет данные заказа в GD (заглушка).

        :param order_id: ID заказа.
        """
        pass


def get_order_service() -> OrderService:
    """
    Возвращает экземпляр сервиса для работы с заказами.

    :return: Экземпляр OrderService.
    """
    return OrderService(
        repo=get_order_repo(),
        response_schema=OrderSchemaOut,
        request_schema=OrderSchemaIn,
        request_service=get_skb_service(),
        file_repo=get_file_repo(),
        event_schema=Event,
    )
