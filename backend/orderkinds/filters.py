from fastapi_filter.contrib.sqlalchemy import Filter

from backend.orderkinds.models import OrderKind


__all__ = ("OrderKindFilter",)


class OrderKindFilter(Filter):
    """
    Фильтр для модели OrderKind.

    Атрибуты:
        name__like (str | None): Фильтр по названию вида заказа с использованием оператора LIKE.
        description__like (str | None): Фильтр по описанию вида заказа с использованием оператора LIKE.
        skb_uuid__like (str | None): Фильтр по UUID SKB с использованием оператора LIKE.

    Константы:
        model: Модель, к которой применяется фильтр (OrderKind).
    """

    name__like: str | None = None
    description__like: str | None = None
    skb_uuid__like: str | None = None

    class Constants(Filter.Constants):
        """
        Константы для фильтра.

        Атрибуты:
            model: Модель, к которой применяется фильтр.
        """

        model = OrderKind
