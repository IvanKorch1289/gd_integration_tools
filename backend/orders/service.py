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
from backend.core.settings import settings
from backend.core.storage import S3Service, s3_bucket_service_factory
from backend.core.utils import utilities
from backend.files.repository import FileRepository
from backend.orders.repository import OrderRepository
from backend.orders.schemas import OrderSchemaOut, PublicSchema


__all__ = ("OrderService",)


class OrderService(BaseService):

    repo = OrderRepository()
    file_repo = FileRepository()
    request_service = APISKBService()
    response_schema = OrderSchemaOut

    async def add(self, data: dict) -> PublicSchema | None:
        try:
            order = await super().add(data=data)

            if order:
                from backend.core.tasks import celery_app

                celery_app.send_task("send_requests_for_create_order", args=[order.id])

                return order
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def create_skb_order(self, order_id: int) -> OrderSchemaOut | None:
        try:
            order = await self.get(key="id", value=order_id)

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
                return result
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=exc
            )

    @utilities.caching(expire=300)
    async def get_order_result(self, order_id: int, response_type: ResponseTypeChoices):
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
            traceback.print_exc(file=sys.stdout)
            return exc

    @utilities.caching(expire=300)
    async def get_order_file_and_json_from_skb(self, order_id: int):
        order = await self.get(key="id", value=order_id)

        if isinstance(order, self.response_schema):
            order = order.model_dump()

        if order.get("is_active", None):
            pdf_response: JSONResponse = await self.get_order_result(
                order_id=order_id,
                response_type=ResponseTypeChoices.pdf,
            )
            json_response: JSONResponse = await self.get_order_result(
                order_id=order_id,
                response_type=ResponseTypeChoices.json,
            )

            if (
                json_response.status_code == status.HTTP_200_OK
                and pdf_response.status_code == status.HTTP_200_OK
            ):
                await self.update(key="id", value=order_id, data={"is_active": False})

        return order

    async def get_order_file_from_storage(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        order = await self.repo.get(key="id", value=order_id)

        files_list = []

        for file in order.files:
            file_uuid = str(file.object_uuid)
            files_list.append(file_uuid)

        if len(files_list) == 1:
            file_uuid = files_list[0]
            return await get_streaming_response(file_uuid, s3_service)
        elif len(files_list) > 1:
            return await create_zip_streaming_response(files_list, s3_service)

    @utilities.caching(expire=300)
    async def get_order_file_from_storage_base64(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        order = await self.repo.get(key="id", value=order_id)

        files_list = []

        for file in order.files:
            base64_file = await get_base64_file(str(file.object_uuid), s3_service)
            files_list.append({"file": base64_file})

        return JSONResponse(
            status_code=status.HTTP_200_OK, content={"files": files_list}
        )

    @utilities.caching(expire=300)
    async def get_order_file_from_storage_link(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        order = await self.get(key="id", value=order_id)

        files_links = []
        files_list = []
        if isinstance(order, dict):
            files_list = order.get("files", None)
        else:
            files_list = [file.model_dump() for file in order.files]

        for file in files_list:
            file_link = await s3_service.generate_download_url(
                str(file.get("object_uuid"))
            )
            files_links.append({"file": file_link})

        return files_links

    @utilities.caching(expire=300)
    async def get_order_file_link_and_json_result_for_request(
        self, order_id: int, s3_service: S3Service = Depends(s3_bucket_service_factory)
    ):
        order = await self.get(key="id", value=order_id)

        order = order if isinstance(order, dict) else order.model_dump()

        data = {
            "data": order.get("response_data", None),
            "errors": order.get("errors", None),
        }

        file_links = []

        if order.get("files", None):
            file_links = await self.get_order_file_from_storage_link(
                order_id=order_id, s3_service=s3_service
            )

        data["file_links"] = file_links

        return data

    @utilities.caching(expire=300)
    async def send_data_to_gd(self, order_id: int):
        pass
