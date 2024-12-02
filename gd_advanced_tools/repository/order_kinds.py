from gd_advanced_tools.models import OrderKind
from gd_advanced_tools.repository.base import SQLAlchemyRepository
from gd_advanced_tools.schemas import OrderKindSchemaOut


__all__ = ("OrderKindRepository",)


class OrderKindRepository(SQLAlchemyRepository):
    model = OrderKind
    response_schema = OrderKindSchemaOut
