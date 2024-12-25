from backend.base.repository import SQLAlchemyRepository
from backend.order_kinds.models import OrderKind
from backend.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindRepository",)


class OrderKindRepository(SQLAlchemyRepository):
    model = OrderKind
    response_schema = OrderKindSchemaOut
    load_joinded_models = False
