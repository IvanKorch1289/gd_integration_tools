"""S168 W15 P2-10: filter_schemas для Orders.

S168 W15 P2-10: moved from src/backend/schemas/filter_schemas/orders.py
to extensions/core_entities/orders/schemas/filter.py per master prompt v8 P2-10.
"""

from __future__ import annotations

from uuid import UUID

from fastapi_filter.contrib.sqlalchemy import Filter

# S106 W4: Order model migrated to extensions/core_entities/orders/domain/models/.
# S168 W14 P2-10 closure: updated from legacy src.backend.core.domain.models.orders.
from extensions.core_entities.orders.domain.models import Order  # noqa: E402,F401

__all__ = ("OrderFilter",)


class OrderFilter(Filter):
    """
    Фильтр для модели Order.

    Атрибуты:
        pledge_gd_id__in (list[int] | None): Фильтр по списку идентификаторов объектов залога в GD.
        pledge_cadastral_number__like (str | None): Фильтр по кадастровому номеру объекта залога с использованием оператора LIKE.
        order_kind_id__in (list[int] | None): Фильтр по списку идентификаторов видов запросов.
        is_active (bool | None): Фильтр по активности заказа.
        is_send_to_gd (bool | None): Фильтр по статусу отправки заказа в ГД.
        object_uuid__like (UUID | None): Фильтр по UUID объекта с использованием оператора LIKE.
        is_send_request_to_skb (bool | None): Фильтр по статусу отправки запроса в СКБ.

    Константы:
        model: Модель, к которой применяется фильтр (Order).
    """

    pledge_gd_id__in: list[int] | None = None
    pledge_cadastral_number__like: str | None = None
    order_kind_id__in: list[int] | None = None
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
