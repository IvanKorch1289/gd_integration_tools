from __future__ import annotations

from typing import TypeAlias

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.errors import DatabaseError
from src.backend.infrastructure.logging import get_logger

db_logger = get_logger("database")


DatabaseSettings: TypeAlias = (
    DatabaseConnectionSettings | ExternalDatabaseConnectionSettings
)


class ExternalDatabaseRegistry:
    """
    Реестр внешних БД.

    Поднимает и хранит инициализаторы внешних подключений
    по `profile_name`.
    """

    def __init__(self, configs: dict[str, ExternalDatabaseConnectionSettings]):
        self.logger = db_logger
        self._initializers: dict[str, DatabaseInitializer] = {}

        for profile_name, config in configs.items():
            self._initializers[profile_name] = DatabaseInitializer(
                settings=config, name=profile_name
            )

    def get_initializer(self, profile_name: str) -> DatabaseInitializer:
        """
        Возвращает инициализатор внешней БД по profile_name.
        """
        initializer = self._initializers.get(profile_name)

        if initializer is None:
            raise DatabaseError(
                message=f"Внешняя БД '{profile_name}' не зарегистрирована"
            )

        return initializer

    def get_bundle(self, profile_name: str) -> DatabaseBundle:
        """
        Возвращает bundle внешней БД по profile_name.
        """
        return self.get_initializer(profile_name).as_bundle()

    def list_profiles(self) -> list[str]:
        """
        Возвращает список зарегистрированных профилей.
        """
        return list(self._initializers.keys())

    async def check_connection(self, profile_name: str) -> bool:
        """
        Проверяет доступность конкретной внешней БД.
        """
        return await self.get_initializer(profile_name).check_connection()

    async def initialize_all_pools(self) -> None:
        """
        Прогревает пулы всех активных внешних БД.
        """
        for initializer in self._initializers.values():
            await initializer.initialize_async_pool()

    async def close_all(self) -> None:
        """
        Закрывает соединения всех внешних БД.
        """
        for initializer in self._initializers.values():
            await initializer.close()
