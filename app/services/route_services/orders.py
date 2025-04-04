from typing import Any, Dict, List

from fastapi import status
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
from app.services.infra_services.s3 import S3Service, get_s3_service_dependency
from app.services.route_services.base import BaseService
from app.services.route_services.skb import APISKBService, get_skb_service
from app.utils.decorators.caching import response_cache
from app.utils.decorators.singleton import singleton
from app.utils.enums.skb import ResponseTypeChoices
from app.utils.errors import NotFoundError, ServiceError
from app.utils.utils import utilities


__all__ = ("get_order_service",)


@singleton
class OrderService(
    BaseService[
        OrderRepository, OrderSchemaOut, OrderSchemaIn, OrderVersionSchemaOut
    ]
):
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
        self.s3_service = s3_service

    async def _get_order_data(self, order_id: int) -> Dict[str, Any]:
        """Получение и преобразование данных заказа"""
        order = await self.get(key="id", value=order_id)
        if not order:
            raise NotFoundError("Заказ не найден")
        return order.model_dump() if isinstance(order, BaseSchema) else order

    async def _get_order_files(self, order_data: Dict) -> List[str]:
        return [
            str(file["object_uuid"]) for file in order_data.get("files", [])
        ]

    async def add(self, data: Dict[str, Any]) -> BaseSchema | None:
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
                    message=order,
                    stream=settings.redis.get_stream_name("order-pipeline"),
                )
            return order
        except Exception as exc:
            raise ServiceError from exc

    async def create_skb_order(self, order_id: int) -> Dict[str, Any]:
        """
        Создает заказ в СКБ-Техно на основе существующего заказа.

        :param order_id: ID заказа.
        :return: Ответ от СКБ-Техно или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при создании заказа в СКБ-Техно.
        """
        try:
            order_data = await self._get_order_data(order_id=order_id)

            # Проверяем, активен ли заказ
            if order_data["is_active"]:
                # Формируем данные для запроса в СКБ-Техно
                data = {
                    "Id": str(order_data["object_uuid"]),
                    "OrderId": str(order_data["object_uuid"]),
                    "Number": order_data["pledge_cadastral_number"],
                    "Priority": settings.skb_api.default_priority,
                    "RequestType": order_data["order_kind"]["skb_uuid"],
                }

                # Отправляем запрос в СКБ-Техно
                result: Dict[str, Any] = (
                    await self.request_service.add_request(data=data)
                )

                # Если запрос успешен, обновляем статус заказа
                if result["status_code"] == status.HTTP_200_OK:
                    await self.repo.update(
                        key="id",
                        value=order_data["id"],
                        data={
                            "is_send_request_to_skb": True,
                            "response_data": result.get("data"),
                        },
                        load_into_memory=False,
                    )
                return {"instance": order_data, "response": result}
            else:
                raise ValueError("Заказ не активен")
        except Exception as exc:
            raise ServiceError from exc

    async def async_create_skb_order(self, order_id: int) -> Dict[str, Any]:
        """
        Создает заказ в СКБ-Техно на основе существующего заказа фоноыой задачей.

        :param order_id: ID заказа.
        :return: Ответ от СКБ-Техно или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при создании заказа в СКБ-Техно.
        """
        try:
            order_data = await self._get_order_data(order_id=order_id)

            # Проверяем, активен ли заказ
            if order_data["is_active"]:
                await stream_client.publish_to_redis(
                    message=order_data,
                    stream=settings.redis.get_stream_name("order-send"),
                )
                return order_data
            else:
                raise ValueError("Заказ не активен")
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_result(
        self, order_id: int, response_type: ResponseTypeChoices
    ) -> Any:
        """
        Получает результат заказа из СКБ-Техно в указанном формате (JSON или PDF).

        :param order_id: ID заказа.
        :param response_type: Тип ответа (JSON или PDF).
        :return: JSONResponse с результатом или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении результата.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )

            order_data = await self._get_order_data(order_id=order_id)

            # Запрашиваем результат из СКБ-Техно
            result = await self.request_service.get_response_by_order(
                order_uuid=order_data["object_uuid"],
                response_type_str=response_type.value,
            )

            content = {}

            if isinstance(result, bytes):
                # Исправленный ключ и параметры загрузки
                await self.s3_service.upload_file(
                    key=str(order_data["object_uuid"]),
                    original_filename=f"{order_data['object_uuid']}.pdf",
                    content=result,
                )

                file = await self.file_repo.add(
                    data={
                        "object_uuid": order_data["object_uuid"],
                    }
                )

                await self.file_repo.add_link(
                    data={"order_id": order_data["id"], "file_id": file.id}
                )
            elif result.get("content_type") == "application/json":
                # Обновляем данные заказа в базе
                content = {
                    "instance": order_data,
                }

                data = result["data"]

                await self.repo.update(
                    key="id",
                    value=order_data["id"],
                    data={
                        "errors": data["Message"],
                        "response_data": data["Data"],
                    },
                    load_into_memory=False,
                )
                content["response"] = result
            else:
                # Обработка других типов данных, если необходимо
                content["response"] = None
            return content
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_file_and_json_from_skb(
        self, order_id: int
    ) -> Dict[str, Any] | None:
        """
        Получает файл и JSON-результат заказа из СКБ-Техно.

        :param order_id: ID заказа.
        :return: Данные заказа или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении данных.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )

            # Получаем заказ по ID
            order_data = await self._get_order_data(order_id=order_id)

            # Если заказ не активен, возвращаем сообщение
            if not order_data["is_active"]:
                return {"hasError": True, "message": "Inactive order"}

            # Запрашиваем результаты последовательно
            json_res = await self.get_order_result(
                order_id, ResponseTypeChoices.json
            )

            if json_res["response"]["data"]["Result"]:
                await self.get_order_result(order_id, ResponseTypeChoices.pdf)

            # Обрабатываем результаты
            update_data = {}
            update_data["response_data"] = json_res.get("response", {}).get(
                "data", {}
            )

            # Если оба запроса успешны, обновляем статус заказа
            clearing_res = await utilities.safe_get(
                json_res, "response.data.Message", "Не готов"
            )

            if not clearing_res:
                update_data["is_active"] = False

            await self.repo.update(
                key="id",
                value=order_id,
                data=update_data,
                load_into_memory=False,
            )

            return json_res
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_file_from_storage(self, order_id: int) -> Any:
        """
        Получает файл заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Потоковое содержимое файла или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении файла.
        """
        try:
            order_data = await self._get_order_data(order_id=order_id)
            files = await self._get_order_files(order_data=order_data)

            if not files:
                return None

            return (
                await self.s3_service.create_zip_archive(files)
                if len(files) > 1
                else await self.s3_service.download_file(files[0])
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_file_from_storage_base64(
        self, order_id: int
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Получает файл заказа из хранилища S3 в формате base64.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: JSONResponse с файлами в формате base64 или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении файла.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )

            order_data = await self._get_order_data(order_id)

            files = [
                {
                    "file": await self.s3_service.get_file_base64(
                        key=str(file["object_uuid"])
                    )
                }
                for file in order_data.get("files", [])
            ]
            return {"files": files}
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_file_from_storage_link(
        self,
        order_id: int,
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Получает ссылки для скачивания файлов заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Список ссылок для скачивания файлов или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении ссылок.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )

            order_data = await self._get_order_data(order_id=order_id)

            files = [
                {
                    "file": await self.s3_service.generate_download_url(
                        key=str(file["object_uuid"])
                    )
                }
                for file in order_data.get("files", [])
            ]
            return {"links": files}

        except Exception as exc:
            raise ServiceError from exc

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
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            # Получаем заказ по ID
            order_data = await self._get_order_data(order_id=order_id)

            # Формируем данные для ответа
            response = {
                "data": order_data.get("response_data", None),
                "errors": order_data.get("errors", None),
            }
            if order_data.get("files"):
                files_links = await self.get_order_file_from_storage_link(
                    order_id=order_id
                )
                response["file_links"] = utilities.safe_get(
                    files_links,
                    "content.files_links",
                )

            return response
        except Exception as exc:
            raise ServiceError from exc

    async def get_order_file_base64_and_json_result_for_request(
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
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            # Получаем заказ по ID
            order_data = await self._get_order_data(order_id=order_id)

            # Формируем данные для ответа
            response = {
                "data": order_data.get("response_data", None),
                "errors": order_data.get("errors", None),
            }
            if order_data.get("files"):
                files_base64 = await self.get_order_file_from_storage_base64(
                    order_id=order_id
                )
                response["file_links"] = files_base64.get("files")

            return response
        except Exception as exc:
            raise ServiceError from exc

    async def async_get_order_file_and_json_from_skb(
        self,
        order_id: int,
    ) -> Dict[str, Any]:
        """
        Получает файл и JSON-результат заказа фоновой задачей.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Данные заказа, включая ссылки на файлы и JSON-результат, или None, если произошла ошибка.
        :raises Exception: Если произошла ошибка при получении данных.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            # Получаем заказ по ID
            order_data = await self._get_order_data(order_id=order_id)

            await stream_client.publish_to_redis(
                message=order_data,
                stream=settings.redis.get_stream_name("order-get-result"),
            )

            return order_data
        except Exception as exc:
            raise ServiceError from exc

    async def send_order_data(self, order_id: int) -> Dict[str, Any] | None:
        """
        Отправляет данные заказа.

        :param order_id: ID заказа.
        """
        try:
            await response_cache.invalidate_pattern(
                pattern=self.__class__.__name__
            )
            # Получаем заказ по ID
            order_data = (
                await self.get_order_file_base64_and_json_result_for_request(
                    order_id=order_id
                )
            )

            result: Dict[str, Any] = {
                "response": order_data.get("data", {}).get("Data", {}),
                "errors": order_data.get("data", {}).get("errors", {}),
                "files": order_data.get("data", {}).get("files", []),
            }

            await stream_client.publish_to_rabbit(
                message=result,
                queue=settings.queue.get_queue_name("order-send"),
            )

            await self.repo.update(
                key="id",
                value=order_id,
                data={"is_send_to_gd": True, "is_active": False},
                load_into_memory=False,
            )

            return order_data
        except Exception as exc:
            raise ServiceError from exc


def get_order_service() -> OrderService:
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
        s3_service=get_s3_service_dependency(),
    )
