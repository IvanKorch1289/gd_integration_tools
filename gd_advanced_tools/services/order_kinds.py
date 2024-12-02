from gd_advanced_tools.repository import OrderKindRepository
from gd_advanced_tools.schemas import OrderKindSchemaOut
from gd_advanced_tools.services.base import BaseService


__all__ = ("OrderKindService",)


class OrderKindService(BaseService):

    repo = OrderKindRepository()
    response_schema = OrderKindSchemaOut
