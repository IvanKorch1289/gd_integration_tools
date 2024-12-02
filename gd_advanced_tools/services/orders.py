import sys
import traceback

from gd_advanced_tools.core.settings import settings
from gd_advanced_tools.enums.api_skb import ResponseTypeChoices
from gd_advanced_tools.repository import OrderRepository
from gd_advanced_tools.repository.files import FileRepository
from gd_advanced_tools.schemas import OrderSchemaOut, PublicModel
from gd_advanced_tools.services.api_skb import APISKBService
from gd_advanced_tools.services.base import BaseService


__all__ = ("OrderService",)


class OrderService(BaseService):

    repo = OrderRepository()
    file_repo = FileRepository()
    request_service = APISKBService()
    response_schema = OrderSchemaOut

    async def add(self, data: dict) -> PublicModel | None:
        kind_uuid = data["order_kind_id"]
        order = await super().add(data=data)
        if order:
            data = {}
            data["Id"] = order.object_uuid
            data["OrderId"] = order.object_uuid
            data["Number"] = order.pledge_cadastral_number
            data["Priority"] = settings.constants["REQUEST_PRIORITY_DEFAULT"]
            data["RequestType"] = kind_uuid
            try:
                request = await self.request_service.add_request(data=data)
                if not request.get("Result"):
                    update_data = {}
                    update_data["is_active"] = False
                    update_data["errors"] = request["Message"]
                    await self.repo.update(key="id", value=order.id, data=update_data)

                    return "Ошибка отправки запроса в СКБ-Техно"
            except Exception as ex:
                traceback.print_exc(file=sys.stdout)
                return ex
            return request
        return order

    async def get_order_result(self, order_id: int, response_type: ResponseTypeChoices):
        try:
            instance = await self.repo.get(key="id", value=order_id)
            result = await self.request_service.get_response_by_order(
                order_uuid=instance.object_uuid, response_type=response_type.value
            )
            if response_type.value == "JSON" and result["Result"]:
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
        except Exception:
            traceback.print_exc(file=sys.stdout)
            return "Ошибка"
