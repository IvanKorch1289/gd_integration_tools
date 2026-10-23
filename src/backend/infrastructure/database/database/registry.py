from __future__ import annotations

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.errors import DatabaseError
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.database.bundle import DatabaseBundle
from src.backend.infrastructure.database.database.initializer import DatabaseInitializer

db_logger = get_logger("database")


type DatabaseSettings = DatabaseConnectionSettings | ExternalDatabaseConnectionSettings


class ExternalDatabaseRegistry:
    """Реестр внешних БД.

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
        """Возвращает инициализатор внешней БД по profile_name."""
        initializer = self._initializers.get(profile_name)

        if initializer is None:
            raise DatabaseError(
                message=f"Внешняя БД '{profile_name}' не зарегистрирована"
            )

        return initializer

    def get_bundle(self, profile_name: str) -> DatabaseBundle:
        """Возвращает bundle внешней БД по profile_name."""
        return self.get_initializer(profile_name).as_bundle()

    def list_profiles(self) -> list[str]:
        """Возвращает список зарегистрированных профилей."""
        return list(self._initializers.keys())

    async def check_connection(self, profile_name: str) -> bool:
        """Проверяет доступность конкретной внешней БД."""
        return await self.get_initializer(profile_name).check_connection()

    async def initialize_all_pools(self) -> None:
        """Прогревает пулы всех активных внешних БД.

        Cycle 172 (MEDIUM-10): метод существовал, но **не имел ни одного
        вызывающего** — пулы внешних БД никогда не прогревались, и первый
        запрос к внешнему профилю платил cold-start latency.

        Отказ одного профиля не должен срывать прогрев остальных, поэтому
        ошибки изолируются по профилю.
        """
        for profile_name, initializer in self._initializers.items():
            try:
                await initializer.initialize_async_pool()
            except Exception as exc:
                self.logger.warning(
                    "Не удалось прогреть пул внешней БД '%s': %s", profile_name, exc
                )

    async def close_all(self) -> None:
        """Закрывает соединения всех внешних БД."""
        for initializer in self._initializers.values():
            await initializer.close()
