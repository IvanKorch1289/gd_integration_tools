from gd_advanced_tools.base.repository import SQLAlchemyRepository
from gd_advanced_tools.order_kinds.models import OrderKind
from gd_advanced_tools.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindRepository",)


class OrderKindRepository(SQLAlchemyRepository):
    model = OrderKind
    response_schema = OrderKindSchemaOut
