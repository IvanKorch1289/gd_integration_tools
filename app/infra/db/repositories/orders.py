from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.infra.db.models.orders import Order
from app.infra.db.repositories.base import SQLAlchemyRepository
from app.utils.decorators.sessioning import session_manager
from app.utils.errors import NotFoundError, handle_db_errors


__all__ = (
    "OrderRepository",
    "get_order_repo",
)


class OrderRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей заказов (Order).

    Атрибуты:
        model (Type[Order]): Модель таблицы заказов.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию True).
        order_kind_repo (OrderKindRepository): Репозиторий для работы с видами заказов.
    """

    class HelperMethods(SQLAlchemyRepository.HelperMethods):
        """
        Вспомогательные методы для работы с базой данных.
        """

        def __init__(
            self,
            order_kind_repo: SQLAlchemyRepository,
            model: Any = Order,
            load_joined_models: bool = True,
        ):
            """
            Инициализация репозитория.

            :param model: Модель таблицы заказов.
            :param load_joined_models: Флаг для загрузки связанных моделей.
            :param order_kind_repo: Репозиторий для работы с видами заказов.
            """
            super().__init__(
                model=model, load_joined_models=load_joined_models
            )
            self.order_kind_repo = order_kind_repo

        async def _validate_order_kind(
            self, data: Dict[str, Any]
        ) -> Dict[str, Any]:
            """
            Валидирует и обновляет данные заказа, проверяя наличие связанного вида заказа.

            :param data: Данные для создания или обновления заказа.
            :return: Обновленные данные заказа.
            :raises NotFoundError: Если связанный вид заказа не найден.
            """
            # Получаем вид заказа по skb_uuid
            kind = await self.order_kind_repo.get(
                key="skb_uuid", value=data["order_kind_id"]
            )
            if not kind:
                # Если вид заказа не найден, выбрасываем исключение
                raise NotFoundError(message="Order kind not found")
            # Обновляем order_kind_id в данных заказа
            data["order_kind_id"] = kind.id
            return data

    def __init__(
        self,
        order_kind_repo: SQLAlchemyRepository,
        model: Any = Order,
        load_joined_models: bool = True,
    ):
        """
        Инициализация репозитория.

        :param model: Модель таблицы заказов.
        :param load_joined_models: Флаг для загрузки связанных моделей.
        :param order_kind_repo: Репозиторий для работы с видами заказов.
        """
        super().__init__(model=model, load_joined_models=load_joined_models)
        self.order_kind_repo = order_kind_repo
        self.helper = self.HelperMethods(
            model=model,
            load_joined_models=load_joined_models,
            order_kind_repo=order_kind_repo,
        )

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(
        self, session: AsyncSession, data: Dict[str, Any]
    ) -> Optional[Order]:
        """
        Добавляет новый заказ в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания заказа.
        :return: Созданный заказ или None, если не удалось найти связанный вид заказа.
        :raises NotFoundError: Если связанный вид заказа не найден.
        :raises DatabaseError: Если произошла ошибка при добавлении заказа.
        """
        # Валидируем и обновляем данные заказа
        data = await self.helper._validate_order_kind(data)
        # Вызываем метод add базового класса для создания заказа
        return await super().add(data=data)

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def update(
        self, session: AsyncSession, key: str, value: Any, data: Dict[str, Any]
    ) -> Optional[Order]:
        """
        Обновляет заказ в таблице.

        :param session: Асинхронная сессия SQLAlchemy.
        :param key: Название поля для поиска заказа.
        :param value: Значение поля для поиска заказа.
        :param data: Данные для обновления заказа.
        :return: Обновленный заказ или None, если не удалось найти связанный вид заказа.
        :raises NotFoundError: Если связанный вид заказа не найден.
        :raises DatabaseError: Если произошла ошибка при обновлении заказа.
        """
        # Если ключ поиска - skb_uuid, валидируем и обновляем данные заказа
        if key == "skb_uuid":
            data = await self.helper._validate_order_kind(data)

        # Вызываем метод update базового класса для обновления заказа
        updated_order = await super().update(key=key, value=value, data=data)
        if not updated_order:
            # Если заказ не найден, выбрасываем исключение
            raise NotFoundError(message="Order not found")

        return updated_order


def get_order_repo() -> OrderRepository:
    """
    Возвращает экземпляр репозитория для работы с заказами.

    Используется как зависимость в FastAPI для внедрения репозитория в сервисы или маршруты.

    :param order_kind_repo: Репозиторий для работы с видами заказов.
    :return: Экземпляр OrderRepository.
    """
    from app.infra.db.repositories.orderkinds import get_order_kind_repo

    return OrderRepository(
        model=Order,
        load_joined_models=True,
        order_kind_repo=get_order_kind_repo(),
    )
