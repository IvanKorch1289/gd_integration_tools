from typing import Any

from fastapi import status
from pydantic import BaseModel

from app.core.config.settings import settings
from app.core.decorators.caching import response_cache
from app.core.enums.skb import ResponseTypeChoices
from app.core.errors import NotFoundError
from app.infrastructure.external_apis.s3 import S3Service, get_s3_service_dependency
from app.infrastructure.repositories.files import FileRepository, get_file_repo
from app.infrastructure.repositories.orders import OrderRepository, get_order_repo
from app.schemas.base import BaseSchema
from app.schemas.route_schemas.orders import (
    OrderSchemaIn,
    OrderSchemaOut,
    OrderVersionSchemaOut,
)
from app.services.core.base import BaseService
from app.services.integrations.skb import APISKBService, get_skb_service
from app.utilities.utils import utilities

__all__ = ("OrderService", "get_order_service")


class OrderService(
    BaseService[OrderRepository, OrderSchemaOut, OrderSchemaIn, OrderVersionSchemaOut]
):
    """
    Сервис для работы с заказами.

    Отвечает за:
    - CRUD-операции поверх заказов;
    - отправку запросов в СКБ-Техно;
    - получение JSON/PDF-результатов;
    - работу с файловым хранилищем.
    (Асинхронное исполнение вынесено в слой Action Bus DSL).
    """

    def __init__(
        self,
        schema_in: type[BaseModel],
        schema_out: type[BaseModel],
        version_schema: type[BaseModel],
        repo: OrderRepository,
        file_repo: FileRepository,
        request_service: APISKBService,
        s3_service: S3Service,
    ) -> None:
        super().__init__(
            repo=repo,
            request_schema=schema_in,
            response_schema=schema_out,
            version_schema=version_schema,
        )
        self.file_repo = file_repo
        self.request_service = request_service
        self.s3_service = s3_service

    async def _get_order_data(self, order_id: int) -> dict[str, Any]:
        """Получает заказ и приводит его к словарю."""
        order = await self.get(key="id", value=order_id)
        if not order:
            raise NotFoundError("Заказ не найден")
        return order.model_dump() if isinstance(order, BaseSchema) else order

    async def _get_order_files(self, order_data: dict[str, Any]) -> list[str]:
        """Возвращает список UUID файлов заказа."""
        return [
            str(file_data["object_uuid"]) for file_data in order_data.get("files", [])
        ]

    async def _invalidate_cache(self) -> None:
        """Инвалидирует кэш по имени сервиса."""
        await response_cache.invalidate_pattern(
            pattern=self.__class__.__name__
        )

    async def create_skb_order(self, order_id: int) -> dict[str, Any]:
        """Создаёт запрос в СКБ-Техно по существующему заказу."""
        async with self._service_error_boundary():
            order_data = await self._get_order_data(order_id=order_id)

            if not order_data["is_active"]:
                raise ValueError("Заказ не активен")

            data = {
                "Id": str(order_data["object_uuid"]),
                "OrderId": str(order_data["object_uuid"]),
                "Number": order_data["pledge_cadastral_number"],
                "Priority": settings.skb_api.default_priority,
                "RequestType": order_data["order_kind"]["skb_uuid"],
            }

            result: dict[str, Any] = await self.request_service.add_request(data=data)

            if result.get("status_code") == status.HTTP_200_OK:
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

    async def get_order_result(
        self, order_id: int, response_type: ResponseTypeChoices
    ) -> Any:
        """Получает результат заказа из СКБ-Техно в указанном формате."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            result = await self.request_service.get_response_by_order(
                order_uuid=order_data["object_uuid"],
                response_type_str=response_type.value,
            )

            content: dict[str, Any] = {"instance": order_data}

            if isinstance(result, bytes):
                await self.s3_service.upload_file(
                    key=str(order_data["object_uuid"]),
                    original_filename=f"{order_data['object_uuid']}.pdf",
                    content=result,
                )

                file_instance = await self.file_repo.add(
                    data={"object_uuid": order_data["object_uuid"]}
                )

                await self.file_repo.add_link(
                    data={"order_id": order_data["id"], "file_id": file_instance.id}
                )

                content["response"] = {
                    "content_type": "application/pdf",
                    "stored": True,
                }
                return content

            if (
                isinstance(result, dict)
                and result.get("content_type") == "application/json"
            ):
                data = result.get("data", {})

                await self.repo.update(
                    key="id",
                    value=order_data["id"],
                    data={
                        "errors": data.get("Message"),
                        "response_data": data.get("Data"),
                    },
                    load_into_memory=False,
                )

                content["response"] = result
                return content

            content["response"] = None
            return content

    async def get_order_file_and_json_from_skb(
        self, order_id: int
    ) -> dict[str, Any] | None:
        """Получает JSON-результат и, если он готов, PDF-файл заказа из СКБ."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            if not order_data["is_active"]:
                return {"hasError": True, "message": "Inactive order"}

            json_result = await self.get_order_result(
                order_id=order_id, response_type=ResponseTypeChoices.json
            )

            has_pdf_result = await utilities.safe_get(
                json_result, "response.data.Result", False
            )

            if has_pdf_result:
                await self.get_order_result(
                    order_id=order_id, response_type=ResponseTypeChoices.pdf
                )

            update_data: dict[str, Any] = {
                "response_data": json_result.get("response", {}).get("data", {})
            }

            message = await utilities.safe_get(
                json_result, "response.data.Message", "Не готов"
            )

            if not message:
                update_data["is_active"] = False

            await self.repo.update(
                key="id", value=order_id, data=update_data, load_into_memory=False
            )

            return json_result

    async def get_order_file_from_storage(self, order_id: int) -> Any:
        """Получает файл (или ZIP) заказа из S3."""
        async with self._service_error_boundary():
            order_data = await self._get_order_data(order_id=order_id)
            files = await self._get_order_files(order_data=order_data)

            if not files:
                return None

            if len(files) > 1:
                return await self.s3_service.create_zip_archive(files)

            return await self.s3_service.download_file(files[0])

    async def get_order_file_from_storage_base64(
        self, order_id: int
    ) -> dict[str, list[dict[str, str]]]:
        """Получает файлы заказа из S3 в формате Base64."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            files = [
                {
                    "file": await self.s3_service.get_file_base64(
                        key=str(file_data["object_uuid"])
                    )
                }
                for file_data in order_data.get("files", [])
            ]

            return {"files": files}

    async def get_order_file_from_storage_link(
        self, order_id: int
    ) -> dict[str, list[dict[str, str]]]:
        """Получает ссылки на скачивание файлов заказа из S3."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            links = [
                {
                    "file": await self.s3_service.generate_download_url(
                        key=str(file_data["object_uuid"])
                    )
                }
                for file_data in order_data.get("files", [])
            ]

            return {"links": links}

    async def get_order_file_link_and_json_result_for_request(
        self, order_id: int
    ) -> dict[str, Any]:
        """Возвращает JSON-результат заказа и ссылки на файлы."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            response: dict[str, Any] = {
                "data": order_data.get("response_data"),
                "errors": order_data.get("errors"),
            }

            if order_data.get("files"):
                files_links = await self.get_order_file_from_storage_link(
                    order_id=order_id
                )
                response["file_links"] = files_links.get("links", [])

            return response

    async def get_order_file_base64_and_json_result_for_request(
        self, order_id: int
    ) -> dict[str, Any]:
        """Возвращает JSON-результат заказа и файлы в формате Base64."""
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_data = await self._get_order_data(order_id=order_id)

            response: dict[str, Any] = {
                "data": order_data.get("response_data"),
                "errors": order_data.get("errors"),
            }

            if order_data.get("files"):
                files_base64 = await self.get_order_file_from_storage_base64(
                    order_id=order_id
                )
                response["files"] = files_base64.get("files", [])

            return response

    async def send_order_data(self, order_id: int) -> dict[str, Any] | None:
        """Формирует полный payload заказа для отправки.

        Фактическая отправка в шину выполняется через
        invocation/handler на стороне DSL/Workflow.
        """
        async with self._service_error_boundary():
            await self._invalidate_cache()

            order_payload = (
                await self.get_order_file_base64_and_json_result_for_request(
                    order_id=order_id
                )
            )

            result: dict[str, Any] = {
                "response": order_payload.get("data", {}),
                "errors": order_payload.get("errors", {}),
                "files": order_payload.get("files", []),
            }

            await self.repo.update(
                key="id",
                value=order_id,
                data={"is_send_to_gd": True, "is_active": False},
                load_into_memory=False,
            )

            return result


_order_service_instance: OrderService | None = None


def get_order_service() -> OrderService:
    """Возвращает lazy-инициализированный экземпляр сервиса работы с заказами.

    Lazy-init нужна т.к. зависимости (репозитории, s3, skb) доступны только
    после полной инициализации приложения — на top-level импорте их ещё нет.
    """
    global _order_service_instance
    if _order_service_instance is None:
        _order_service_instance = OrderService(
            repo=get_order_repo(),
            schema_out=OrderSchemaOut,
            schema_in=OrderSchemaIn,
            version_schema=OrderVersionSchemaOut,
            request_service=get_skb_service(),
            file_repo=get_file_repo(),
            s3_service=get_s3_service_dependency(),
        )
    return _order_service_instance
