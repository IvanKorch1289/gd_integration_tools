"""Wave 13 Q9 — graceful degradation sync-engine при неразрешимом драйвере.

Контракт (Wave F.3, async-first): если sync-драйвер недоступен, старт НЕ
валится — ``sync_engine=None``, warning в лог, async-путь продолжает
работать. Wave 13 Q9 добавил в этот сценарий ``DatabaseDriverError``
(драйвер не объявлен ни в одном extra проекта) — раньше такой случай
доходил до рантайма как ``ModuleNotFoundError`` внутри SQLAlchemy.
"""

from __future__ import annotations

import pytest

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.enums.database import DatabaseTypeChoices


@pytest.mark.unit
class TestSyncEngineGracefulDegradation:
    """Sync-engine опционален: недоступный драйвер не валит старт."""

    def test_sync_engine_none_for_undeclared_sync_driver(self) -> None:
        """Необъявленный sync-драйвер → ``sync_engine=None`` без исключения."""
        from src.backend.infrastructure.database.database.initializer import (
            DatabaseInitializer,
        )

        settings = DatabaseConnectionSettings(
            type=DatabaseTypeChoices.postgresql,
            host="db.internal",
            port=5432,
            name="app",
            username="u",
            password="p",
            sync_driver="psycopg2",  # не объявлен ни в одном extra
        )
        initializer = DatabaseInitializer(settings=settings, name="probe")

        assert initializer.sync_engine is None
        assert initializer.sync_session_maker is None
        assert initializer.async_engine is not None
        assert initializer.async_session_maker is not None

    def test_sync_engine_created_for_declared_sync_driver(self) -> None:
        """Объявленный и установленный драйвер → sync-engine создаётся."""
        from src.backend.infrastructure.database.database.initializer import (
            DatabaseInitializer,
        )

        settings = DatabaseConnectionSettings(
            type=DatabaseTypeChoices.postgresql,
            host="db.internal",
            port=5432,
            name="app",
            username="u",
            password="p",
            sync_driver="psycopg",
        )
        initializer = DatabaseInitializer(settings=settings, name="probe")

        assert initializer.sync_engine is not None
        assert initializer.sync_session_maker is not None
