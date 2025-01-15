from backend.base.repository import SQLAlchemyRepository
from backend.order_kinds.models import OrderKind
from backend.order_kinds.schemas import OrderKindSchemaOut


__all__ = ("OrderKindRepository",)


class OrderKindRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей видов запросов (OrderKind).

    Наследует функциональность базового репозитория (SQLAlchemyRepository) и
    предоставляет методы для взаимодействия с данными видов запросов.

    Атрибуты:
        model (OrderKind): Модель таблицы видов запросов.
        response_schema (OrderKindSchemaOut): Схема для преобразования данных в ответ.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    model = OrderKind
    response_schema = OrderKindSchemaOut
    load_joined_models = False
