from typing import Any, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from backend.base.repository import SQLAlchemyRepository
from backend.core.database import session_manager
from backend.core.errors import DatabaseError, NotFoundError
from backend.orderkinds.repository import OrderKindRepository
from backend.orders.models import Order
from backend.orders.schemas import OrderSchemaOut


__all__ = ("OrderRepository",)


class OrderRepository(SQLAlchemyRepository):
    """
    Репозиторий для работы с таблицей заказов (Order).

    Атрибуты:
        model (Type[Order]): Модель таблицы заказов.
        response_schema (Type[OrderSchemaOut]): Схема для преобразования данных в ответ.
        load_joined_models (bool): Флаг для загрузки связанных моделей (по умолчанию False).
    """

    model = Order
    response_schema = OrderSchemaOut
    load_joined_models = False

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
        try:
            kind = await OrderKindRepository().get(
                key="skb_uuid", value=data["order_kind_id"]
            )
            if not kind:
                raise NotFoundError(message="Order kind not found")

            data["order_kind_id"] = kind.id
            return await super().add(data=data)
        except NotFoundError:
            raise
        except Exception as exc:
            raise DatabaseError(message=f"Failed to add order: {str(exc)}")

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
        try:
            if key == "skb_uuid":
                kind = await OrderKindRepository().get(
                    key="skb_uuid", value=data["order_kind_id"]
                )
                if not kind:
                    raise NotFoundError(message="Order kind not found")
                data["order_kind_id"] = kind.id

            updated_order = await super().update(key=key, value=value, data=data)
            if not updated_order:
                raise NotFoundError(message="Order not found")

            return updated_order
        except NotFoundError:
            raise
        except Exception as exc:
            raise DatabaseError(message=f"Failed to update order: {str(exc)}")
