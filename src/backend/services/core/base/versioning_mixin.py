from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from src.backend.core.decorators.caching import response_cache
from src.backend.core.logging import get_logger

logger = get_logger("services.core.base.versioning")
from src.backend.schemas.base import BaseSchema


def _is_orm_model(instance: Any) -> bool:
    cls = instance.__class__
    return hasattr(cls, "__tablename__") and hasattr(cls, "__table__")


class VersioningMixin:
    """versioning (all versions, latest, restore, changes) для BaseService. S61 W1 extraction."""

    __slots__ = ()

    @response_cache
    async def get_all_object_versions(
        self, object_id: int, order: str = "asc"
    ) -> list[BaseSchema | None]:
        """Получает все версии объекта.

        Args:
            object_id: ID объекта.
            order: Направление сортировки.

        Returns:
            Список версий в виде схем.
        """
        async with self._service_error_boundary():
            versions = await self.repo.get_all_versions(
                object_id=object_id, order=order
            )

            result: list[BaseSchema | None] = []
            for version in versions:
                try:
                    response = await self.helper._transfer(version, self.version_schema)
                    result.append(response)
                except Exception as _:
                    logger.exception(
                        "Ошибка преобразования версии object_id=%s", object_id
                    )

            return result

    @response_cache
    async def get_latest_object_version(self, object_id: int) -> BaseSchema | None:
        """Получает последнюю версию объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Последняя версия или ``None``.
        """
        async with self._service_error_boundary():
            version = await self.repo.get_latest_version(object_id=object_id)
            return await self.helper._transfer(version, self.version_schema)

    async def restore_object_to_version(
        self, object_id: int, transaction_id: int
    ) -> BaseSchema | None:
        """Восстанавливает объект до указанной версии.

        Args:
            object_id: ID объекта.
            transaction_id: ID транзакции для восстановления.

        Returns:
            Восстановленный объект или ``None``.
        """
        async with self._service_error_boundary():
            restored_object = await self.repo.restore_to_version(
                object_id=object_id, transaction_id=transaction_id
            )
            return await self.helper._transfer(restored_object, self.response_schema)

    async def get_object_changes(self, object_id: int) -> list[dict[str, Any]]:
        """Получает список изменений атрибутов объекта.

        Args:
            object_id: ID объекта.

        Returns:
            Список изменений между версиями.
        """
        async with self._service_error_boundary():
            versions = await self.get_all_object_versions(object_id=object_id)
            if not versions:
                return []

            versions_dict = [
                (version.model_dump() if isinstance(version, BaseSchema) else version)
                for version in versions
            ]

            changes: list[dict[str, Any]] = []
            excluded_fields = {"transaction_id", "operation_type"}

            for i in range(1, len(versions_dict)):
                prev_version = versions_dict[i - 1]
                current_version = versions_dict[i]

                diff = {
                    attr: {
                        "old": prev_version.get(attr),
                        "new": current_version.get(attr),
                    }
                    for attr in prev_version.keys() | current_version.keys()
                    if attr not in excluded_fields
                    and prev_version.get(attr) != current_version.get(attr)
                }

                if diff:
                    changes.append(
                        {
                            "transaction_id": current_version.get("transaction_id"),
                            "operation_type": current_version.get("operation_type"),
                            "changes": diff,
                        }
                    )

            return changes
