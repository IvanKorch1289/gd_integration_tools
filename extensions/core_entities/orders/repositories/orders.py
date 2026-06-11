"""Репозиторий Order (миграция из ядра — Sprint 7, R-V15-16).

Каноническое расположение в V11 plugin layout. Старый модуль
``src.backend.infrastructure.repositories.orders`` сохраняется как
backward-compat shim и эмитит DeprecationWarning.

Зависит от ``get_order_kind_repo()`` — берём из shim'а
``infrastructure.repositories.orderkinds``, чтобы не дублировать
loaders. После flip плагины перейдут на прямой импорт из
``extensions.core_entities.orderkinds.repositories.orderkinds``.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from extensions.core_entities.orders.domain.models import Order
from src.backend.core.errors import NotFoundError
from src.backend.infrastructure.database.session_manager import main_session_manager
from src.backend.infrastructure.repositories.base import SQLAlchemyRepository
from src.backend.infrastructure.repositories.orderkinds import get_order_kind_repo

__all__ = ("OrderRepository", "get_order_repo")


class OrderRepository(SQLAlchemyRepository):
    """Репозиторий для таблицы заказов (Order)."""

    class HelperMethods(SQLAlchemyRepository.HelperMethods):
        """Вспомогательные методы валидации order_kind_id."""

        async def _validate_order_kind(self, data: dict[str, Any]) -> dict[str, Any]:
            """Резолвит ``order_kind_id`` через OrderKind репозиторий.

            Args:
                data: Данные заказа со ссылкой на kind через ``skb_uuid``.

            Returns:
                Обновлённые данные с подменённым ``order_kind_id``.

            Raises:
                NotFoundError: Если соответствующий kind не найден.
            """
            kind = await self.order_kind_repo.get(  # type: ignore[attr-defined]
                key="skb_uuid", value=data["order_kind_id"]
            )
            if not kind:
                raise NotFoundError(message="Order kind not found")
            data["order_kind_id"] = kind.id
            return data

    def __init__(
        self,
        order_kind_repo: SQLAlchemyRepository,
        model: Any = Order,
        load_joined_models: bool = True,
    ) -> None:
        """Инициализация репозитория.

        Args:
            order_kind_repo: Репозиторий для OrderKind (DI).
            model: Модель заказов.
            load_joined_models: Загружать ли связанные модели.
        """
        super().__init__(model=model, load_joined_models=load_joined_models)
        self.order_kind_repo = order_kind_repo
        self.helper.order_kind_repo = order_kind_repo  # type: ignore[attr-defined]

    @main_session_manager.connection()
    async def add(self, session: AsyncSession, data: dict[str, Any]) -> Order | None:
        """Создание заказа с валидацией kind."""
        data = await self.helper._validate_order_kind(data)  # type: ignore[attr-defined]
        return await super().add(data=data)

    @main_session_manager.connection()
    async def update(
        self,
        session: AsyncSession,
        key: str,
        value: Any,
        data: dict[str, Any],
        load_into_memory: bool = True,
    ) -> Order | None:
        """Обновление заказа.

        При ``key='skb_uuid'`` дополнительно перевалидируется kind.
        """
        if key == "skb_uuid":
            data = await self.helper._validate_order_kind(data)  # type: ignore[attr-defined]
        updated = await super().update(
            key=key, value=value, data=data, load_into_memory=load_into_memory
        )
        if not updated:
            raise NotFoundError(message="Order not found")
        return updated


_order_repo_instance: OrderRepository | None = None


def get_order_repo() -> OrderRepository:
    """Возвращает singleton экземпляр :class:`OrderRepository`."""
    global _order_repo_instance
    if _order_repo_instance is None:
        _order_repo_instance = OrderRepository(
            model=Order, load_joined_models=True, order_kind_repo=get_order_kind_repo()
        )
    return _order_repo_instance
