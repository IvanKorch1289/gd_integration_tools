from typing import List
from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

from backend.orders.models import Order


__all__ = ("OrderFilter",)


class OrderFilter(Filter):
    pledge_gd_id__in: List[int] | None = None
    pledge_cadastral_number__like: str | None = None
    order_kind_id__in: List[int] | None = None
    is_active: bool | None = None
    is_send_to_gd: bool | None = None
    object_uuid__like: UUID | None = None
    is_send_request_to_skb: bool | None = None

    class Constants(Filter.Constants):
        model = Order
