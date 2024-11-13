from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

from gd_advanced_tools.models import Order


__all__ = ('OrderFilter', )


class OrderFilter(Filter):
    pledge_gd_id__in: int | None = None
    pledge_cadastral_number__like: str | None = None
    order_kind_id__in: int | None = None
    is_active: bool | None = None
    is_send_to_gd: bool | None = None
    object_uuid__like: UUID | None = None

    class Constants(Filter.Constants):
        model = Order
