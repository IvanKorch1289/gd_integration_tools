from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass


from fastapi_filter.contrib.sqlalchemy import Filter
from fastapi_pagination import Page, Params

from src.backend.core.decorators.caching import response_cache


def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


class CrudMixin:
    """CRUD operations (add/add_many/update/get/get_or_add/get_first_or_last_with_limit/delete) для BaseService. S61 W1 extraction."""

    __slots__ = ()

    async def add(self, data: dict[str, Any]) -> ConcreteResponseSchema | None:
        """Добавляет объект и инвалидирует кэш.

        Args:
            data: Данные для создания объекта.

        Returns:
            Схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            result: (
                ConcreteResponseSchema | None
            ) = await self.helper._process_and_transfer(
                "add", self.response_schema, data=data
            )
            entity_id = getattr(result, "id", None)
            await self._invalidate_entity_cache(entity_id=entity_id)
            return result

    async def add_many(
        self, data_list: list[dict[str, Any]]
    ) -> list[ConcreteResponseSchema | None]:
        """Добавляет несколько объектов.

        При ошибке элемент записывается как ``None``, ошибка
        логируется и сохраняется. После обработки всех элементов,
        если были ошибки, поднимается ``ServiceError`` с деталями.

        Args:
            data_list: Список данных для создания.

        Returns:
            Список схем ответа (``None`` для ошибочных элементов).

        Raises:
            ServiceError: Если хотя бы один элемент не был создан.
        """
        result: list[ConcreteResponseSchema | None] = []
        errors: list[dict[str, Any]] = []

        for idx, data in enumerate(data_list):
            try:
                response: ConcreteResponseSchema | None = await self.add(data=data)
                result.append(response)
            except Exception as exc:
                logger.exception(
                    "Ошибка при добавлении объекта #%d в add_many: %s", idx, data
                )
                result.append(None)
                errors.append({"index": idx, "data": data, "error": str(exc)})

        if errors:
            from src.backend.core.errors import ServiceError

            raise ServiceError(
                detail=(
                    f"add_many: {len(errors)}/{len(data_list)} элементов не создано. "
                    f"Ошибки: {errors}"
                )
            )

        return result

    async def update(
        self, key: str, value: int, data: dict[str, Any]
    ) -> ConcreteResponseSchema | None:
        """Обновляет объект в репозитории.

        Args:
            key: Название поля.
            value: Значение поля.
            data: Данные для обновления.

        Returns:
            Обновлённая схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            result = await self.helper._process_and_transfer(
                "update", self.response_schema, key=key, value=value, data=data
            )
            await self._invalidate_entity_cache(entity_id=value)
            return result

    @response_cache
    async def get(
        self,
        key: str | None = None,
        value: int | None = None,
        filter: Filter | None = None,
        pagination: Params | None = None,
        by: str = "id",
        order: str = "asc",
    ) -> (
        ConcreteResponseSchema
        | list[ConcreteResponseSchema]
        | Page[ConcreteResponseSchema]
        | None
    ):
        """Получает объекты по ключу, фильтру или все.

        Args:
            key: Название поля (опционально).
            value: Значение поля (опционально).
            filter: Фильтр для запроса (опционально).
            pagination: Параметры пагинации.
            by: Поле сортировки.
            order: Направление сортировки.

        Returns:
            Схема, список схем, ``Page`` или ``None``.
        """
        async with self._service_error_boundary():
            result = await self.helper._process_and_transfer(
                "get",
                self.response_schema,
                key=key,
                value=value,
                filter=filter,
                pagination=pagination,
                order=order,
                by=by,
            )

            if pagination:
                return Page.create(
                    items=result.items, total=result.total, params=pagination
                )
            return result

    async def get_or_add(
        self,
        key: str | None = None,
        value: int | None = None,
        data: dict[str, Any] | None = None,
    ) -> ConcreteResponseSchema | None:
        """Получает объект или создаёт, если не найден.

        Args:
            key: Название поля.
            value: Значение поля.
            data: Данные для создания.

        Returns:
            Схема ответа или ``None``.
        """
        async with self._service_error_boundary():
            instance = None
            if key and value:
                instance = await self.helper._process_and_transfer(
                    "get", self.response_schema, key=key, value=value
                )
            if not instance and data:
                instance = await self.helper._process_and_transfer(
                    "add", self.response_schema, data=data
                )
            return instance

    @response_cache
    async def get_first_or_last_with_limit(
        self, limit: int = 1, by: str = "id", order: str = "asc"
    ) -> ConcreteResponseSchema | list[ConcreteResponseSchema] | None:
        """Возвращает первые/последние записи с лимитом."""
        async with self._service_error_boundary():
            return await self.helper._process_and_transfer(
                "first_or_last", self.response_schema, limit=limit, by=by, order=order
            )

    async def delete(self, key: str, value: int) -> None:
        """Удаляет объект и инвалидирует кэш.

        Args:
            key: Название поля.
            value: Значение поля.
        """
        async with self._service_error_boundary():
            await self.repo.delete(key=key, value=value)
            await self._invalidate_entity_cache(entity_id=value)
