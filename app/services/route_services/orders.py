from typing import Any, Dict, List, Optional

import asyncio
import json_tricks
from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config.settings import settings
from app.repositories.files import FileRepository, get_file_repo
from app.repositories.orders import OrderRepository, get_order_repo
from app.schemas.base import BaseSchema
from app.schemas.route_schemas.orders import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from app.services.infra_services.events import stream_client
from app.services.infra_services.s3 import S3Service, get_s3_service
from app.services.route_services.base import BaseService
from app.services.route_services.skb import APISKBService, get_skb_service
from app.utils.decorators.caching import response_cache
from app.utils.enums.skb import ResponseTypeChoices
from app.utils.logging_service import app_logger, request_logger


__all__ = ("get_order_service",)


class OrderService(BaseService[OrderRepository]):
    """
    Сервис для работы с заказами. Обеспечивает создание, обновление, получение и обработку заказов,
    а также взаимодействие с внешними сервисами (например, СКБ-Техно) и файловым хранилищем.
    """

    def __init__(
        self,
        schema_in: BaseModel,
        schema_out: BaseModel,
        version_schema: BaseModel,
        repo: OrderRepository,
        file_repo: FileRepository,
        request_service: APISKBService,
        s3_service: S3Service,
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
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )
        self.file_repo = file_repo
        self.request_service = request_service
        self.s3_service = get_s3_service()

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
                await stream_client.publish_to_redis(
                    message=order.id, stream="order_send_to_skb_stream"
                )
            return order
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def create_skb_order(
        self, order_id: int
    ) -> Optional[OrderSchemaOut]:
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
            if order.get("is_active", None):  # type: ignore
                # Формируем данные для запроса в СКБ-Техно
                data = {
                    "Id": str(order.get("object_uuid", None)),  # type: ignore
                    "OrderId": str(order.get("object_uuid")),  # type: ignore
                    "Number": order.get("pledge_cadastral_number", None),  # type: ignore
                    "Priority": settings.skb_api.default_priority,
                    "RequestType": order.get("order_kind", None).get(  # type: ignore
                        "skb_uuid", None
                    ),
                }

                # Отправляем запрос в СКБ-Техно
                result = await self.request_service.add_request(data=data)

                # Если запрос успешен, обновляем статус заказа
                if result["status_code"] == status.HTTP_200_OK:
                    await self.update(
                        key="id",
                        value=order.get("id", None),  # type: ignore
                        data={
                            "is_send_request_to_skb": True,
                            "response_data": result.get("data"),
                        },
                    )
                    # Генерируем событие о успешной отправке заказа
                    message_data = {
                        "to_emails": order.get("email_for_answer"),  # type: ignore
                        "subject": f"Order {order.get("object_uuid", None)}",  # type: ignore
                        "message": "Order registration success to SKB completed",
                    }
                    await stream_client.publish_to_redis(
                        message=message_data,
                        stream="email_send_stream",
                    )
                return result
            raise
        except Exception:
            app_logger.error("Error sending request to SKB", exc_info=True)
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
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
                order_uuid=instance.object_uuid,
                response_type=response_type.value,
            )
            return result
            # Обрабатываем JSON-ответ
            if isinstance(result, JSONResponse):
                body = json_tricks.loads(result.body.decode("utf-8"))
                if (
                    not body.get("hasError", "")
                    and response_type.value == "JSON"
                ):
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
                    content={
                        "hasError": False,
                        "message": "file upload to storage",
                    },
                )
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"hasError": True},
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
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
                raise ValueError(
                    f"Expected a dictionary, but got {type(order)}"
                )

            # Если заказ не активен, возвращаем сообщение
            if not order.get("is_active", False):
                return {"hasError": True, "message": "Inactive order"}

            # Запрашиваем JSON и PDF результаты параллельно
            json_response, pdf_response = await asyncio.gather(
                self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.json
                ),
                self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.pdf
                ),
            )

            # Обрабатываем результаты
            update_data = {}
            message = json_response.get("data", {}).get("Message")
            date = json_response.get("data", {}).get("Date")
            result = json_response.get("data", {}).get("Result")

            update_data["response_data"] = f"{message} (date {date})"

            # Если оба запроса успешны, обновляем статус заказа
            if result:
                update_data["is_active"] = False

            await self.update(key="id", value=order_id, data=update_data)

            return json_response
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    async def get_order_file_from_storage(
        self, order_id: int
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
            if len(files_list) > 1:
                return await self.s3_service.download_file(key=files_list[0])
            elif len(files_list) > 1:
                return await self.s3_service.create_zip_archive(
                    keys=files_list
                )

            return None
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
    async def get_order_file_from_storage_base64(
        self, order_id: int
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
                {
                    "file": await self.s3_service.get_file_base64(
                        key=str(file.object_uuid)
                    )
                }
                for file in order.files
            ]
            return JSONResponse(
                status_code=status.HTTP_200_OK, content={"files": files_list}
            )
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
    async def get_order_file_from_storage_link(
        self,
        order_id: int,
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
                    "file": await self.s3_service.generate_download_url(
                        str(file.get("object_uuid"))
                    )
                }
                for file in files_list
            ]
            return files_links
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
    async def get_order_file_link_and_json_result_for_request(
        self,
        order_id: int,
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
                data["file_links"] = (
                    await self.get_order_file_from_storage_link(
                        order_id=order_id, s3_service=self.s3_service
                    )
                )
            return data
        except Exception:
            raise  # Исключение будет обработано глобальным обработчиком

    @response_cache
    async def send_data_to_gd(self, order_id: int) -> None:
        """
        Отправляет данные заказа в GD (заглушка).

        :param order_id: ID заказа.
        """
        pass


def get_order_service() -> BaseService:
    """
    Возвращает экземпляр сервиса для работы с заказами.

    :return: Экземпляр OrderService.
    """
    return OrderService(
        repo=get_order_repo(),
        schema_out=OrderSchemaOut,
        schema_in=OrderSchemaIn,
        version_schema=OrderVersionSchemaOut,
        request_service=get_skb_service(),
        file_repo=get_file_repo(),
        s3_service=get_s3_service(),
    )
