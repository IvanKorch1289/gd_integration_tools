from backend.base.service import BaseService
from backend.order_kinds.repository import OrderKindRepository
from backend.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindService",)


class OrderKindService(BaseService):

    repo = OrderKindRepository()
    response_schema = OrderKindSchemaOut
