from fastapi_filter.contrib.sqlalchemy import Filter

from gd_advanced_tools.models import OrderKind

__all__ = ("OrderKindFilter",)


class OrderKindFilter(Filter):
    name__like: str | None = None
    description__like: str | None = None
    skb_uuid__like: str | None = None

    class Constants(Filter.Constants):
        model = OrderKind
