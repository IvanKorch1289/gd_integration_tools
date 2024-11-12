from gd_advanced_tools.repository.base import SQLAlchemyRepository
from gd_advanced_tools.models.order_kinds import OrderKind


__all__ = ('OrderKindRepository', )


class OrderKindRepository(SQLAlchemyRepository):
    model = OrderKind
