from src.infrastructure.database.models.orderkinds import OrderKind
from src.infrastructure.repositories.base import SQLAlchemyRepository

__all__ = ("OrderKindRepository", "get_order_kind_repo")


class OrderKindRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей видов запросов (OrderKind).

    Наследует функциональность базового репозитория (SQLAlchemyRepository) и
    предоставляет методы для взаимодействия с данными видов запросов.

    Атрибуты:
        model (OrderKind): Модель таблицы видов запросов.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    def __init__(self, model: OrderKind, load_joined_models: bool = False):
        """
        Инициализация репозитория для работы с видами запросов.

        :param model: Модель таблицы видов запросов (OrderKind).
        :param load_joined_models: Флаг для загрузки связанных моделей (по умолчанию False).
        """
        super().__init__(model=model, load_joined_models=load_joined_models)


_order_kind_repo_instance: OrderKindRepository | None = None


def get_order_kind_repo() -> OrderKindRepository:
    """
    Возвращает экземпляр репозитория для работы с видами заказов.

    Используется как зависимость в FastAPI для внедрения репозитория в сервисы или маршруты.

    :return: Экземпляр OrderKindRepository.
    """
    global _order_kind_repo_instance
    if _order_kind_repo_instance is None:
        _order_kind_repo_instance = OrderKindRepository(
            model=OrderKind, load_joined_models=False
        )
    return _order_kind_repo_instance
