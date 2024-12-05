from gd_advanced_tools.base.service import BaseService
from gd_advanced_tools.order_kinds.repository import OrderKindRepository
from gd_advanced_tools.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindService",)


class OrderKindService(BaseService):

    repo = OrderKindRepository()
    response_schema = OrderKindSchemaOut
