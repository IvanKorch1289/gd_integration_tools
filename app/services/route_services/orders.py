import json
from typing import Any, Dict, List, Optional

from fastapi import status
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.config.settings import settings
from app.infra.storage import BaseS3Service, s3_bucket_service_factory
from app.infra.stream_manager import stream_client
from app.repositories.files import FileRepository, get_file_repo
from app.repositories.orders import OrderRepository, get_order_repo
from app.schemas.base import BaseSchema
from app.schemas.route_schemas.orders import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from app.services.helpers.storage_helpers import (
    create_zip_streaming_response,
    get_base64_file,
    get_streaming_response,
)
from app.services.route_services.base import BaseService
from app.services.route_services.skb import APISKBService, get_skb_service
from app.utils.decorators.caching import response_cache
from app.utils.enums.skb import ResponseTypeChoices


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
        s3_service: BaseS3Service,
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
        self.s3_service = s3_service

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
                await stream_client.publish_event(
                    event_type="order_created", data={"order": order.id}
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

            order_data = None

            # Преобразуем данные заказа, если это необходимо
            if isinstance(order, BaseSchema):
                order_data = order.model_dump()

            # Проверяем, активен ли заказ
            if order_data.get("is_active", None):
                # Формируем данные для запроса в СКБ-Техно
                data = {
                    "Id": order_data.get("object_uuid", None),
                    "OrderId": order_data.get("object_uuid", None),
                    "Number": order_data.get("pledge_cadastral_number", None),
                    "Priority": settings.skb_api.default_priority,
                    "RequestType": order_data.get("order_kind", None).get(
                        "skb_uuid", None
                    ),
                }

                # Отправляем запрос в СКБ-Техно
                result = await self.request_service.add_request(data=data)

                # Если запрос успешен, обновляем статус заказа
                if result["status_code"] == status.HTTP_200_OK:
                    await self.update(
                        key="id",
                        value=order_data.get("id", None),
                        data={"is_send_request_to_skb": True},
                    )
                    # Генерируем событие о успешной отправке заказа
                    await stream_client.publish_event(
                        event_type="init_mail_send", data={"order": order}
                    )
                return result
            return order_data
        except Exception:
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

            # Обрабатываем JSON-ответ
            if isinstance(result, JSONResponse):
                body = json.loads(result.body.decode("utf-8"))
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

                return {
                    "hasError": True,
                    "message": "Результат еще не готов",
                }
            return {
                "hasError": True,
                "message": "Inactive order",
            }
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
                return await get_streaming_response(
                    files_list[0], service=self.s3_service
                )
            elif len(files_list) > 1:
                return await create_zip_streaming_response(
                    files_list, self.s3_service
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
                    "file": await get_base64_file(
                        str(file.object_uuid), self.s3_service
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
        s3_service=s3_bucket_service_factory(),
    )
