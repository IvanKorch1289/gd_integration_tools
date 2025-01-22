from typing import Any, Dict, Optional

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import SQLAlchemyRepository
from backend.core.database import session_manager
from backend.core.errors import NotFoundError, handle_db_errors
from backend.orderkinds.repository import (
    OrderKindRepository,
    get_order_kind_repo,
)
from backend.orders.models import Order


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

    def __init__(
        self,
        model: Any = Order,
        load_joined_models: bool = True,
        order_kind_repo: OrderKindRepository = Depends(get_order_kind_repo),
    ):
        """
        Инициализация репозитория.

        :param model: Модель таблицы заказов.
        :param load_joined_models: Флаг для загрузки связанных моделей.
        :param order_kind_repo: Репозиторий для работы с видами заказов (внедряется через Depends).
        """
        super().__init__(model=model, load_joined_models=load_joined_models)
        self.order_kind_repo = order_kind_repo

    async def _validate_order_kind(self, data: Dict[str, Any]) -> Dict[str, Any]:
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

    @handle_db_errors
    @session_manager.connection(isolation_level="SERIALIZABLE", commit=True)
    async def add(self, session: AsyncSession, data: Dict[str, Any]) -> Optional[Order]:
        """
        Добавляет новый заказ в таблицу.

        :param session: Асинхронная сессия SQLAlchemy.
        :param data: Данные для создания заказа.
        :return: Созданный заказ или None, если не удалось найти связанный вид заказа.
        :raises NotFoundError: Если связанный вид заказа не найден.
        :raises DatabaseError: Если произошла ошибка при добавлении заказа.
        """
        # Валидируем и обновляем данные заказа
        data = await self._validate_order_kind(data)
        # Вызываем метод add базового класса для создания заказа
        return await super().add(session=session, data=data)

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
            data = await self._validate_order_kind(data)

        # Вызываем метод update базового класса для обновления заказа
        updated_order = await super().update(
            session=session, key=key, value=value, data=data
        )
        if not updated_order:
            # Если заказ не найден, выбрасываем исключение
            raise NotFoundError(message="Order not found")

        return updated_order


def get_order_repo(
    order_kind_repo: OrderKindRepository = Depends(get_order_kind_repo),
) -> OrderRepository:
    """
    Возвращает экземпляр репозитория для работы с заказами.

    Используется как зависимость в FastAPI для внедрения репозитория в сервисы или маршруты.

    :param order_kind_repo: Репозиторий для работы с видами заказов (внедряется через Depends).
    :return: Экземпляр OrderRepository.
    """
    return OrderRepository(
        model=Order,
        load_joined_models=True,
        order_kind_repo=order_kind_repo,
    )
