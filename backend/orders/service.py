import sys
import traceback

from backend.api_skb.enums import ResponseTypeChoices
from backend.api_skb.service import APISKBService
from backend.base.service import BaseService
from backend.core.settings import settings
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
        order = await super().add(data=data)
        if order:
            data = {
                "Id": order.object_uuid,
                "OrderId": order.object_uuid,
                "Number": order.pledge_cadastral_number,
                "Priority": settings.api_settings.skb_request_priority_default,
                "RequestType": order.order_kind.skb_uuid,
            }
            try:
                response = await self.request_service.add_request(data=data)
                if not response.get("Result"):
                    update_data = {
                        "is_active": False,
                        "is_send_request_to_skb": True,
                        "errors": response.get("Message"),
                    }
                else:
                    update_data = {"is_active": True, "is_send_request_to_skb": True}
                await self.repo.update(key="id", value=order.id, data=update_data)
                return response
            except Exception as ex:
                traceback.print_exc(file=sys.stdout)
                return ex
        return order

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
