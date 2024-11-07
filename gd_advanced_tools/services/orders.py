from gd_advanced_tools.repository.orders import OrderRepository
from gd_advanced_tools.schemas.orders import OrderSchemaOut
from gd_advanced_tools.services.base import BaseService


__all__ = ('OrderService', )


class OrderService(BaseService):

    repo = OrderRepository()
    response_schema = OrderSchemaOut
