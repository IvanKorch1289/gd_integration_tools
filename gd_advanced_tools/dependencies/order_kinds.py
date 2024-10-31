from gd_advanced_tools.repository.order_kinds import OrdersKindRepository
from gd_advanced_tools.services.order_kinds import OrdersKindService


def order_kinds_service():
    return OrdersKindService(OrdersKindRepository)
