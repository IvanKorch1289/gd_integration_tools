from typing import List
from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

from app.infra.db.models import Order


__all__ = ("OrderFilter",)


class OrderFilter(Filter):
    """
    Фильтр для модели Order.

    Атрибуты:
        pledge_gd_id__in (List[int] | None): Фильтр по списку идентификаторов объектов залога в GD.
        pledge_cadastral_number__like (str | None): Фильтр по кадастровому номеру объекта залога с использованием оператора LIKE.
        order_kind_id__in (List[int] | None): Фильтр по списку идентификаторов видов запросов.
        is_active (bool | None): Фильтр по активности заказа.
        is_send_to_gd (bool | None): Фильтр по статусу отправки заказа в ГД.
        object_uuid__like (UUID | None): Фильтр по UUID объекта с использованием оператора LIKE.
        is_send_request_to_skb (bool | None): Фильтр по статусу отправки запроса в СКБ.

    Константы:
        model: Модель, к которой применяется фильтр (Order).
    """

    pledge_gd_id__in: List[int] | None = None
    pledge_cadastral_number__like: str | None = None
    order_kind_id__in: List[int] | None = None
    is_active: bool | None = None
    is_send_to_gd: bool | None = None
    object_uuid__like: UUID | None = None
    is_send_request_to_skb: bool | None = None

    class Constants(Filter.Constants):
        """
        Константы для фильтра.

        Атрибуты:
            model: Модель, к которой применяется фильтр.
        """

        model = Order
