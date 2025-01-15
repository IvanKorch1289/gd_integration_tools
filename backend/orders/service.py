import json
import sys
import traceback

from fastapi import Depends, status
from fastapi.responses import JSONResponse

from backend.api_skb.enums import ResponseTypeChoices
from backend.api_skb.service import APISKBService
from backend.base.service import BaseService
from backend.core.dependencies import (
    create_zip_streaming_response,
    get_base64_file,
    get_streaming_response,
)
from backend.core.logging_config import app_logger
from backend.core.redis import caching_decorator
from backend.core.settings import settings
from backend.core.storage import S3Service, s3_bucket_service_factory
from backend.core.utils import utilities
from backend.files.repository import FileRepository
from backend.orders.filters import OrderFilter
from backend.orders.repository import OrderRepository
from backend.orders.schemas import OrderSchemaOut, PublicSchema


__all__ = ("OrderService",)


class OrderService(BaseService):
    """
    Сервис для работы с заказами. Обеспечивает создание, обновление, получение и обработку заказов,
    а также взаимодействие с внешними сервисами (например, СКБ-Техно) и файловым хранилищем.
    """

    repo = OrderRepository()
    file_repo = FileRepository()
    request_service = APISKBService()
    response_schema = OrderSchemaOut

    async def _send_email(self, to_email: str, subject: str, message: str) -> None:
        """
        Отправляет email с указанным содержимым.

        :param to_email: Адрес электронной почты получателя.
        :param subject: Тема письма.
        :param message: Текст письма.
        """
        try:
            await utilities.send_email(
                to_email=to_email, subject=subject, message=message
            )
        except Exception as exc:
            app_logger.error(f"Failed to send email: {exc}")

    async def _handle_exception(
        self, exc: Exception, order_id: int = None, email: str = None
    ) -> JSONResponse:
        """
        Обрабатывает исключения, логирует их и отправляет email с информацией об ошибке.

        :param exc: Исключение, которое произошло.
        :param order_id: ID заказа (опционально).
        :param email: Адрес электронной почты для отправки уведомления (опционально).
        :return: JSONResponse с информацией об ошибке.
        """
        traceback.print_exc(file=sys.stdout)
        if order_id:
            try:
                order_from_db = await self.get(key="id", value=order_id)
                if order_from_db:
                    email = order_from_db.email_for_answer
            except Exception as db_exc:
                app_logger.error(f"Failed to fetch order from DB: {db_exc}")
        await self._send_email(
            to_email=email if email else "default_email@example.com",
            subject="Новый заказ выписки в СКБ-Техно (ОШИБКА!!!)",
            message=f"Не удалось создать заказ выписки: {exc}",
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=str(exc)
        )

    async def add(self, data: dict) -> PublicSchema | None:
        """
        Создает новый заказ на основе переданных данных.

        :param data: Словарь с данными для создания заказа.
        :return: Созданный заказ или None, если произошла ошибка.
        """
        try:
            order = await super().add(data=data)
            if order:
                check_services = await utilities.health_check_all_services()
                response_body = await utilities.get_response_type_body(check_services)
                if response_body.get("is_all_services_active", None):
                    from core.background_tasks import celery_app

                    celery_app.send_task(
                        "send_requests_for_create_order",
                        args=[order.id],
                        time_limit=settings.bts_settings.bts_max_time_limit,
                    )
                await self._send_email(
                    to_email=data.get("email_for_answer"),
                    subject="Новый заказ выписки в СКБ-Техно",
                    message=f"Номер заказа: {order.object_uuid}",
                )
            return order
        except Exception as exc:
            return await self._handle_exception(exc, email=data.get("email_for_answer"))

    async def add_many(self, data_list: list[dict]) -> list[PublicSchema] | None:
        """
        Создает несколько заказов на основе списка данных.

        :param data_list: Список словарей с данными для создания заказов.
        :return: Список созданных заказов или None, если произошла ошибка.
        """
        try:
            return [await self.get_or_add(data=data) for data in data_list]
        except Exception as exc:
            return await self._handle_exception(exc)

    async def get_or_add(self, data: dict = None) -> PublicSchema | None:
        """
        Получает заказ по параметрам или создает новый, если заказ не найден.

        :param data: Словарь с данными для поиска или создания заказа.
        :return: Найденный или созданный заказ. Возвращает None в случае ошибки.
        """
        try:
            filter_params = {
                "pledge_cadastral_number__like": data.get("pledge_cadastral_number"),
                "is_active": True,
                "is_send_request_to_skb": False,
            }
            instance = await self.get_by_params(
                filter=OrderFilter.model_validate(filter_params)
            )
            if not instance or (isinstance(instance, list) and len(instance) == 0):
                instance = await self.add(data=data)
            return instance
        except Exception as exc:
            return await self._handle_exception(exc)

    async def create_skb_order(self, order_id: int) -> OrderSchemaOut | None:
        """
        Создает заказ в СКБ-Техно на основе существующего заказа.

        :param order_id: ID заказа.
        :return: Ответ от СКБ-Техно или None, если произошла ошибка.
        """
        try:
            order: OrderSchemaOut = await self.get(key="id", value=order_id)
            if isinstance(order, PublicSchema):
                order = order.model_dump()

            if order.get("is_active", None):
                data = {
                    "Id": order.get("object_uuid", None),
                    "OrderId": order.get("object_uuid", None),
                    "Number": order.get("pledge_cadastral_number", None),
                    "Priority": settings.api_skb_settings.skb_request_priority_default,
                    "RequestType": order.get("order_kind", None).get("skb_uuid", None),
                }
                result: JSONResponse = await self.request_service.add_request(data=data)

                if result.status_code == status.HTTP_200_OK:
                    await self.update(
                        key="id",
                        value=order.get("id", None),
                        data={"is_send_request_to_skb": True},
                    )
                    await self._send_email(
                        to_email=order.get("email_for_answer"),
                        subject="Новый заказ выписки в СКБ-Техно",
                        message=f"Заказ выписки по объекту id = {order.get("object_uuid")} зарегистрирован в СКБ-Техно",
                    )
                return result
        except Exception as exc:
            return await self._handle_exception(exc, order_id=order_id)

    @caching_decorator
    async def get_order_result(self, order_id: int, response_type: ResponseTypeChoices):
        """
        Получает результат заказа из СКБ-Техно в указанном формате (JSON или PDF).

        :param order_id: ID заказа.
        :param response_type: Тип ответа (JSON или PDF).
        :return: JSONResponse с результатом или None, если произошла ошибка.
        """
        try:
            instance = await self.repo.get(key="id", value=order_id)
            result = await self.request_service.get_response_by_order(
                order_uuid=instance.object_uuid, response_type=response_type.value
            )
            if isinstance(result, JSONResponse):
                body = json.loads(result.body.decode("utf-8"))
                if not body.get("hasError", "") and response_type.value == "JSON":
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
        except Exception as exc:
            return await self._handle_exception(exc)

    @caching_decorator
    async def get_order_file_and_json_from_skb(self, order_id: int):
        """
        Получает файл и JSON-результат заказа из СКБ-Техно.

        :param order_id: ID заказа.
        :return: Данные заказа или None, если произошла ошибка.
        """
        try:
            order = await self.get(key="id", value=order_id)
            if isinstance(order, self.response_schema):
                order = order.model_dump()
            if not isinstance(order, dict):
                raise ValueError(f"Expected a dictionary, but got {type(order)}")
            if order.get("is_active", None):
                pdf_response: JSONResponse = await self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.pdf
                )
                json_response: JSONResponse = await self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.json
                )
                if (
                    json_response.status_code == status.HTTP_200_OK
                    and pdf_response.status_code == status.HTTP_200_OK
                ):
                    await self.update(
                        key="id", value=order_id, data={"is_active": False}
                    )
            return order
        except Exception as exc:
            return await self._handle_exception(exc, order_id=order_id)

    async def get_order_file_from_storage(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        """
        Получает файл заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Потоковое содержимое файла или None, если произошла ошибка.
        """
        try:
            order = await self.repo.get(key="id", value=order_id)
            files_list = [str(file.object_uuid) for file in order.files]
            if len(files_list) == 1:
                return await get_streaming_response(files_list[0], s3_service)
            elif len(files_list) > 1:
                return await create_zip_streaming_response(files_list, s3_service)
        except Exception as exc:
            return await self._handle_exception(exc)

    @caching_decorator
    async def get_order_file_from_storage_base64(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        """
        Получает файл заказа из хранилища S3 в формате base64.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: JSONResponse с файлами в формате base64 или None, если произошла ошибка.
        """
        try:
            order = await self.repo.get(key="id", value=order_id)
            files_list = [
                {"file": await get_base64_file(str(file.object_uuid), s3_service)}
                for file in order.files
            ]
            return JSONResponse(
                status_code=status.HTTP_200_OK, content={"files": files_list}
            )
        except Exception as exc:
            return await self._handle_exception(exc)

    @caching_decorator
    async def get_order_file_from_storage_link(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        """
        Получает ссылки для скачивания файлов заказа из хранилища S3.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Список ссылок для скачивания файлов или None, если произошла ошибка.
        """
        try:
            order = await self.get(key="id", value=order_id)
            files_list = (
                order.get("files", None)
                if isinstance(order, dict)
                else [file.model_dump() for file in order.files]
            )
            files_links = [
                {
                    "file": await s3_service.generate_download_url(
                        str(file.get("object_uuid"))
                    )
                }
                for file in files_list
            ]
            return files_links
        except Exception as exc:
            return await self._handle_exception(exc)

    @caching_decorator
    async def get_order_file_link_and_json_result_for_request(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        """
        Получает ссылки на файлы и JSON-результат заказа.

        :param order_id: ID заказа.
        :param s3_service: Сервис для работы с S3.
        :return: Данные заказа, включая ссылки на файлы и JSON-результат, или None, если произошла ошибка.
        """
        try:
            order = await self.get(key="id", value=order_id)
            order = order if isinstance(order, dict) else order.model_dump()
            data = {
                "data": order.get("response_data", None),
                "errors": order.get("errors", None),
            }
            if order.get("files", None):
                data["file_links"] = await self.get_order_file_from_storage_link(
                    order_id=order_id, s3_service=s3_service
                )
            return data
        except Exception as exc:
            return await self._handle_exception(exc)

    @caching_decorator
    async def send_data_to_gd(self, order_id: int):
        pass
