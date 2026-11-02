"""ADR-0420 — ротация кредов БД без рестарта + регистратор пула main-БД.

Кластер F5 (волна 24 мультироевого аудита):

* ``get_db_initializer()`` / ``get_external_db_registry()`` — ``lru_cache``-
  синглтоны: engine создаётся **один раз**, поэтому смена DSN (Vault/``.env``
  → ``settings.reload()``, ADR-0372/0379) не подхватывалась до рестарта
  процесса — скомпрометированный пароль продолжал работать в пуле;
* ``_register_db_pool_in_unified_monitor`` — мёртвый код (0 вызовов).

RED-состояние (до правки):

* ``test_engine_recreated_on_dsn_change`` — accessor возвращал **тот же**
  engine после смены DSN (ротации не было вовсе);
* ``test_apply_db_credential_rotation_*`` — async-API ротации не существовало;
* ``test_db_pool_registrar_called_after_rotation`` — регистратор пула
  не вызывался ни разу.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import SecretStr

from src.backend.core.config.settings import settings
from src.backend.infrastructure.database.database import accessors

# ── Подмены без реальных engine'ов ──────────────────────────────────────


class _FakeInitializer:
    """Подмена ``DatabaseInitializer``: без реального engine'а и пула."""

    def __init__(self, settings: Any, name: str) -> None:
        """Запоминает креды, с которыми создан «engine».

        Args:
            settings: Настройки подключения, переданные конструктором.
            name: Имя профиля БД.

        """
        self.settings = settings
        self.name = name
        self.password_at_creation = _password_of(settings)
        self.async_engine = SimpleNamespace(pool=SimpleNamespace(size=lambda: 1))
        self.close = AsyncMock()

    def as_bundle(self) -> Any:
        """Возвращает заглушку bundle'а (сборка нужна только smart-менеджеру)."""
        return SimpleNamespace(
            name=self.name,
            settings=self.settings,
            async_engine=self.async_engine,
            async_session_maker=SimpleNamespace(),
            sync_engine=None,
            sync_session_maker=None,
            replica_engine=None,
            replica_session_maker=None,
        )


class _FakeRegistry:
    """Подмена ``ExternalDatabaseRegistry``: без реальных engine'ов."""

    def __init__(self, configs: Any) -> None:
        """Запоминает конфигурацию профилей.

        Args:
            configs: Словарь профилей внешних БД.

        """
        self.configs = configs
        self.close_all = AsyncMock()


def _password_of(db_settings: Any) -> str | None:
    """Возвращает пароль из настроек подключения (в открытом виде)."""
    password = getattr(db_settings, "password", None)
    if password is None:
        return None
    if isinstance(password, SecretStr):
        return password.get_secret_value()
    return str(password)


@pytest.fixture(autouse=True)
def _reset_db_accessors() -> Any:
    """Сбрасывает кэши accessor'ов БД до и после каждого теста."""
    accessors.get_db_initializer.cache_clear()
    accessors.get_external_db_registry.cache_clear()
    yield
    accessors.get_db_initializer.cache_clear()
    accessors.get_external_db_registry.cache_clear()


@pytest.fixture
def _restore_main_password() -> Any:
    """Восстанавливает пароль main-БД после теста."""
    original = settings.database.password
    yield
    settings.database.password = original


# ── (1) main-БД: ротация по смене DSN ───────────────────────────────────


def test_no_rotation_without_dsn_change() -> None:
    """Без смены DSN engine остаётся тем же — ничего не трогаем.

    До правки дефект был обратным: движок создавался один раз и **никогда**
    не пересоздавался, даже если DSN в настройках менялся.
    """
    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        first = accessors.get_db_initializer()
        second = accessors.get_db_initializer()

    assert first is second, "Без смены DSN engine должен остаться прежним"
    assert first.close.await_count == 0, "Пул не должен закрываться без смены DSN"


@pytest.mark.asyncio
async def test_engine_recreated_on_dsn_change(_restore_main_password: None) -> None:
    """Смена DSN → старый engine закрывается, новый создаётся с новым DSN.

    До правки accessor отдавал старый engine: соединения устанавливались по
    прежнему паролю, а процесс оставался с устаревшими кредами до рестарта.
    """
    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        first = accessors.get_db_initializer()
        assert first.password_at_creation == _password_of(settings.database)

        settings.database.password = SecretStr("rotated-secret")

        second = accessors.get_db_initializer()
        await asyncio.sleep(0.01)

    assert second is not first, "Смена DSN обязана пересоздавать engine"
    assert first.close.await_count == 1, "Старый engine должен быть закрыт (dispose)"
    assert second.password_at_creation == "rotated-secret", (
        "Новый engine должен быть создан с новым DSN"
    )


@pytest.mark.asyncio
async def test_apply_db_credential_rotation_awaits_dispose(
    _restore_main_password: None,
) -> None:
    """Async-API ротации дожидается закрытия старого пула."""
    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        first = accessors.get_db_initializer()

        settings.database.password = SecretStr("rotated-secret")

        rotated = await accessors.apply_db_credential_rotation()

        assert rotated is True, "Ротация обязана сообщить об изменении DSN"
        assert first.close.await_count == 1, "Старый пул должен быть закрыт"

        second = accessors.get_db_initializer()
        assert second is not first
        assert second.password_at_creation == "rotated-secret"


@pytest.mark.asyncio
async def test_apply_db_credential_rotation_noop_without_change() -> None:
    """Без смены DSN async-API не трогает ничего (no-op)."""
    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        first = accessors.get_db_initializer()

        rotated = await accessors.apply_db_credential_rotation()

        assert rotated is False
        assert first.close.await_count == 0
        assert accessors.get_db_initializer() is first


def test_rotation_invalidates_session_manager_caches(
    _restore_main_password: None,
) -> None:
    """Ротация сбрасывает кэш session-менеджеров (иначе они держат старый engine).

    ``get_main_session_manager`` / ``get_smart_session_manager`` /
    ``get_external_session_manager`` кэшируют ``async_sessionmaker``,
    привязанный к engine'у. Без сброса кэша после ротации они продолжали бы
    открывать сессии в уже закрытом пуле.
    """
    from src.backend.infrastructure.database import session_manager

    session_manager.get_main_session_manager.cache_clear()
    session_manager.get_external_session_manager.cache_clear()
    accessors.get_smart_session_manager.cache_clear()

    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        accessors.get_db_initializer()
        settings.database.password = SecretStr("rotated-secret")
        accessors.get_db_initializer()

    assert session_manager.get_main_session_manager.cache_info().currsize == 0
    assert session_manager.get_external_session_manager.cache_info().currsize == 0
    assert accessors.get_smart_session_manager.cache_info().currsize == 0


# ── (2) внешние БД: ротация по смене кредов профиля ──────────────────────


def _fake_external_settings(profiles: dict[str, Any]) -> Any:
    """Собирает заглушку ``settings`` с заданными профилями внешних БД."""
    return SimpleNamespace(
        database=settings.database,
        external_databases=SimpleNamespace(profiles=profiles),
    )


def test_external_registry_recreated_on_credential_change() -> None:
    """Смена креда внешнего профиля → реестр внешних БД пересоздаётся."""
    profile = SimpleNamespace(
        type="postgresql",
        host="ext.internal",
        port=5432,
        db_name="ext",
        username="ext_user",
        password=SecretStr("old-secret"),
        async_driver="asyncpg",
        sync_driver="psycopg",
    )
    fake_settings = _fake_external_settings({"ext_1": profile})

    with (
        patch.object(accessors, "settings", fake_settings),
        patch.object(accessors, "ExternalDatabaseRegistry", _FakeRegistry),
    ):
        first = accessors.get_external_db_registry()
        second = accessors.get_external_db_registry()
        assert first is second, "Без смены кредов реестр не пересоздаётся"

        profile.password = SecretStr("new-secret")

        third = accessors.get_external_db_registry()

    assert third is not first, "Смена креда внешнего профиля обязана пересоздать реестр"


# ── (3) регистратор пула main-БД ────────────────────────────────────────


def test_db_pool_registrar_called_after_rotation() -> None:
    """После ротации пул main-БД пере-регистрируется в мониторах.

    Без пере-регистрации мониторы держали бы объект пула **старого** engine'а
    и пинговали бы его по отозванным кредам.
    """
    from src.backend.infrastructure.database import pool_monitor

    with (
        patch.object(accessors, "DatabaseInitializer", _FakeInitializer),
        patch.object(pool_monitor, "register_db_pool_in_unified_monitor") as registrar,
    ):
        accessors.get_db_initializer()
        settings.database.password = SecretStr("rotated-secret")
        accessors.get_db_initializer()

    registrar.assert_called_once()


def test_db_pool_registrar_registers_pool_in_unified_monitor() -> None:
    """Регистратор реально кладёт пул в ``UnifiedPoolManager`` и ``PoolHealthMonitor``."""
    from src.backend.infrastructure.clients.pool_health import get_pool_monitor
    from src.backend.infrastructure.clients.unified_pool_manager import (
        get_unified_pool_manager,
    )
    from src.backend.infrastructure.database import pool_monitor

    with patch.object(accessors, "DatabaseInitializer", _FakeInitializer):
        pool_monitor.register_db_pool_in_unified_monitor()

    manager = get_unified_pool_manager()
    assert "db_main" in manager.list_pools(), (
        "Пул main-БД должен быть зарегистрирован в UnifiedPoolManager"
    )
    assert "db_main" in get_pool_monitor()._pools, (
        "Пул main-БД должен быть зарегистрирован в PoolHealthMonitor"
    )
