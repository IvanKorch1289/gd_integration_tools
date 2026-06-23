"""S168 W15 P2-10: filter_schemas для Orderkinds.

S168 W15 P2-10: moved from src/backend/schemas/filter_schemas/orderkinds.py
to extensions/core_entities/orderkinds/schemas/filter.py per master prompt v8 P2-10.
"""

from fastapi_filter.contrib.sqlalchemy import Filter

# S106 W3: OrderKind model migrated to extensions/core_entities/orderkinds/domain/models/.
# S168 W14 P2-10 closure: updated from legacy src.backend.core.domain.models.orderkinds.
from extensions.core_entities.orderkinds.domain.models import (  # noqa: E402,F401
    OrderKind,
)

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
