"""W14.5 — фабрика :class:`WatermarkStore` по конфигу.

Используется в composition root (``register_app_state``) для выбора
конкретного бэкенда (``memory``/``postgres``) на основании
:class:`WatermarkSettings`. Фабрика лениво импортирует PG-реализацию,
чтобы dev_light-окружения без psycopg/SQLAlchemy не платили за импорт.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.infrastructure.watermark.memory_store import MemoryWatermarkStore

if TYPE_CHECKING:
    from src.backend.core.config.services.watermark import WatermarkSettings
    from src.backend.infrastructure.database.session_manager import (
        DatabaseSessionManager,
    )

__all__ = ("create_watermark_store",)


def create_watermark_store(
    settings: WatermarkSettings,
    *,
    session_manager: DatabaseSessionManager | None = None,
) -> WatermarkStore:
    """Создаёт ``WatermarkStore`` по выбранному бэкенду.

    Args:
        settings: ``WatermarkSettings`` (выбор backend, debounce).
        session_manager: ``DatabaseSessionManager`` главной БД; обязателен
            для ``backend="postgres"``.

    Returns:
        Конкретная реализация :class:`WatermarkStore`.

    Raises:
        RuntimeError: при ``backend="postgres"`` без ``session_manager``.
    """
    match settings.backend:
        case "memory":
            return MemoryWatermarkStore()
        case "postgres":
            if session_manager is None:
                raise RuntimeError(
                    "PostgresWatermarkStore требует DatabaseSessionManager; "
                    "передайте main_session_manager в composition root."
                )
            from src.backend.infrastructure.watermark.postgres_store import (
                PostgresWatermarkStore,
            )

            return PostgresWatermarkStore(session_manager)
