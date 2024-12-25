import sys
import traceback

from backend.api_skb.enums import ResponseTypeChoices
from backend.api_skb.service import APISKBService
from backend.base.service import BaseService
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
        from celery_app.tasks.send_requests_by_one import send_requests_by_one

        try:
            order = await super().add(data=data)
            if order:
                send_requests_by_one.delay(order_id=order.id)
                return order
        except Exception as ex:
            traceback.print_exc(file=sys.stdout)
            return ex

    async def get_order_result(self, order_id: int, response_type: ResponseTypeChoices):
        try:
            instance = await self.repo.get(key="id", value=order_id)
            result = await self.request_service.get_response_by_order(
                order_uuid=instance.object_uuid, response_type=response_type.value
            )
            if response_type.value == "JSON" and result.get("Result"):
                update_data = {
                    "is_active": False,
                    "errors": result.get("Message"),
                    "response_data": result.get("Data"),
                }
                await self.repo.update(key="id", value=instance.id, data=update_data)
                return result["Data"]
            if response_type.value == "PDF":
                file = await self.file_repo.add(
                    data={"object_uuid": instance.object_uuid}
                )
                await self.file_repo.add_link(
                    data={"order_id": instance.id, "file_id": file.id}
                )
                return file
            return result
        except Exception as exc:
            traceback.print_exc(file=sys.stdout)
            return {"error": str(exc)}

    async def get_order_file_and_json(self, order_id: int):
        filter = {"is_active": True, "is_send_request_to_skb": True, "id": order_id}

        order = self.get_by_params(filter=filter)

        if order:
            pdf_response = await self.get_order_result(
                order_id=order_id,
                response_type=ResponseTypeChoices.pdf,
            )
            json_response = await self.get_order_result(
                order_id=order_id,
                response_type=ResponseTypeChoices.json,
            )
            if pdf_response and json_response:
                await self.update(key="id", value=order_id, data={"is_active": False})
        return None
