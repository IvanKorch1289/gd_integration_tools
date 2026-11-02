from __future__ import annotations

import asyncio
import hashlib
import importlib
import inspect
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.external_databases import (
    ExternalDatabaseConnectionSettings,
)
from src.backend.core.config.settings import settings
from src.backend.core.logging import get_logger
from src.backend.infrastructure.database.database.initializer import (
    DatabaseInitializer,  # S67 W3: fix NameError (TD-pre-existing)
)
from src.backend.infrastructure.database.database.registry import (
    ExternalDatabaseRegistry,  # S67 W3: fix NameError (TD-pre-existing)
)

if TYPE_CHECKING:
    from src.backend.core.config.hot_reload import ConfigHotReloader

db_logger = get_logger("database")

__all__ = (
    "apply_db_credential_rotation",
    "get_db_initializer",
    "get_db_manager",
    "get_db_session",
    "get_external_db_registry",
    "get_smart_session_manager",
    "register_db_credential_rotation_callback",
)


type DatabaseSettings = DatabaseConnectionSettings | ExternalDatabaseConnectionSettings


# ─── ADR-0420: ротация кредов БД ────────────────────────────────────────
#
# Синглтоны main-БД и внешних БД создавались ОДИН раз (``lru_cache``), а
# движки с DSN — в момент создания. Поэтому смена DSN (Vault/``.env`` →
# ``settings.reload()``, ADR-0372/0379) подхватывалась только после рестарта
# процесса: пул продолжал работать с отозванными кредами.
#
# Механизм: рядом с объектом хранится **отпечаток кредов** (SHA-256, без
# секрета в открытом виде), с которыми он создан. При каждом обращении к
# accessor'у отпечаток сверяется с текущими настройками; при расхождении
# старый пул закрывается (dispose), кэш сбрасывается, а новый объект
# создаётся с актуальным DSN.


#: Поля настроек подключения, участвующие в отпечатке кредов.
_CREDENTIAL_FIELDS: tuple[str, ...] = (
    "type",
    "host",
    "port",
    "name",
    "db_name",
    "service_name",
    "sid",
    "username",
    "async_driver",
    "sync_driver",
    "path",
)


@dataclass(slots=True)
class _CredentialState:
    """Снимок кредов, с которыми создан текущий DB-объект.

    Attributes:
        fingerprint: SHA-256 отпечаток набора кредов.
        instance: Объект, владеющий созданным engine'ом/реестром.

    """

    fingerprint: str
    instance: Any


#: Снимок кредов main-БД (None — accessor ещё не вызывался).
_main_db_state: _CredentialState | None = None

#: Снимок кредов реестра внешних БД (None — accessor ещё не вызывался).
_external_registry_state: _CredentialState | None = None


def _secret_text(value: Any) -> str | None:
    """Разворачивает секрет (``SecretStr`` → str) для вычисления отпечатка.

    Args:
        value: Значение секрета (``SecretStr``, ``str`` или ``None``).

    Returns:
        Значение секрета в открытом виде либо ``None``.

    """
    if value is None:
        return None
    if isinstance(value, SecretStr):
        return value.get_secret_value()
    return str(value)


def _credential_fingerprint(db_settings: Any) -> str:
    """Вычисляет SHA-256 отпечаток кредов подключения к БД.

    В отпечаток входят хост/порт/логин/пароль/драйверы и DSN реплики.
    Секрет в открытом виде не сохраняется (только хэш) — отпечаток
    безопасно держать в памяти и сравнивать.

    Args:
        db_settings: Настройки подключения (``DatabaseConnectionSettings``
            либо ``ExternalDatabaseConnectionSettings``).

    Returns:
        HEX-хэш SHA-256 от набора кредов.

    """
    parts: list[str] = [
        str(getattr(db_settings, field, "")) for field in _CREDENTIAL_FIELDS
    ]
    parts.append(_secret_text(getattr(db_settings, "password", None)) or "")
    parts.append(_secret_text(getattr(db_settings, "replica_dsn", None)) or "")
    payload = "\x00".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _external_profiles_fingerprint() -> str:
    """Отпечаток кредов всех профилей внешних БД.

    Args:
        None.

    Returns:
        HEX-хэш SHA-256 от набора кредов всех профилей.

    """
    try:
        profiles = getattr(settings.external_databases, "profiles", {}) or {}
    except Exception:  # noqa: BLE001 — конфигурация внешних БД может быть невалидна
        return ""
    parts: list[str] = []
    for profile_name in sorted(profiles):
        parts.append(profile_name)
        parts.append(_credential_fingerprint(profiles[profile_name]))
    payload = "\x00".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _dispose_callable(instance: Any) -> Any:
    """Вызывает ``close()``/``close_all()`` объекта и возвращает awaitable.

    Args:
        instance: Объект с методом ``close`` (``DatabaseInitializer``) или
            ``close_all`` (``ExternalDatabaseRegistry``).

    Returns:
        Awaitable закрытия или ``None``, если закрывать нечего.

    """
    for method_name in ("close", "close_all"):
        closer = getattr(instance, method_name, None)
        if callable(closer):
            result = closer()
            return result if inspect.isawaitable(result) else None
    return None


def _log_dispose_failure(task: asyncio.Task[Any]) -> None:
    """Логирует ошибку фонового закрытия пула БД.

    Args:
        task: Задача закрытия пула.

    Returns:
        None.

    """
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        db_logger.error("Ошибка закрытия пула БД при ротации кредов: %s", exc)


def _schedule_dispose(instance: Any, label: str) -> None:
    """Планирует закрытие старого пула БД (sync-код не может ``await``).

    Args:
        instance: Объект с методом ``close``/``close_all``.
        label: Имя пула для логов (``main`` / ``external``).

    Returns:
        None.

    """
    awaitable = _dispose_callable(instance)
    if awaitable is None:
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is None:
        close = getattr(awaitable, "close", None)
        if callable(close):
            close()
        db_logger.warning(
            "Ротация кредов БД '%s': нет event loop — async-пул не закрыт, "
            "соединения освободятся только при рестарте процесса",
            label,
        )
        return
    task = loop.create_task(awaitable)
    task.add_done_callback(_log_dispose_failure)


async def _dispose_awaitable(awaitable: Any) -> None:
    """Дожидается закрытия пула БД (ошибка закрытия не роняет ротацию).

    Args:
        awaitable: Awaitable закрытия пула.

    Returns:
        None.

    """
    if awaitable is None:
        return
    try:
        await awaitable
    except Exception as exc:  # noqa: BLE001 — закрытие не должно ронять ротацию
        db_logger.error("Ошибка закрытия пула БД при ротации кредов: %s", exc)


def _invalidate_session_caches() -> None:
    """Сбрасывает кэши session-менеджеров после ротации кредов.

    ``get_main_session_manager`` / ``get_smart_session_manager`` /
    ``get_external_session_manager`` кэшируют ``async_sessionmaker``,
    привязанный к engine'у. Без сброса они продолжали бы открывать сессии
    в уже закрытом пуле.

    Returns:
        None.

    """
    get_smart_session_manager.cache_clear()
    try:
        # ponytail: importlib вместо прямого импорта — прямой импорт
        # создаёт цикл accessors → session_manager → database → accessors,
        # который ломает разрешение типов в mypy (модуль-пакет становится
        # «unfollowed» → его атрибуты типизируются как Any?).
        session_manager = importlib.import_module(
            "src.backend.infrastructure.database.session_manager"
        )
    except ImportError:  # pragma: no cover — модуль всегда доступен в проекте
        return
    session_manager.get_main_session_manager.cache_clear()
    session_manager.get_external_session_manager.cache_clear()


def _refresh_db_pool_registration(instance: Any) -> None:
    """Пере-регистрирует пул main-БД в мониторах после ротации.

    Args:
        instance: Новый ``DatabaseInitializer`` (с новым engine'ом).

    Returns:
        None.

    """
    try:
        pool_monitor = importlib.import_module(
            "src.backend.infrastructure.database.pool_monitor"
        )

        pool_monitor.register_db_pool_in_unified_monitor(instance)
    except Exception as exc:  # noqa: BLE001 — регистрация не критична для БД
        db_logger.warning("Пере-регистрация пула main-БД не удалась: %s", exc)


def _detect_main_rotation() -> _CredentialState | None:
    """Определяет смену DSN main-БД и сбрасывает зависимые кэши.

    Returns:
        Снимок старого состояния (если креды изменились) либо ``None``.

    """
    global _main_db_state

    state = _main_db_state
    if state is None:
        return None
    if state.fingerprint == _credential_fingerprint(settings.database):
        return None
    _main_db_state = None
    _build_db_initializer.cache_clear()
    _invalidate_session_caches()
    return state


def _detect_external_rotation() -> _CredentialState | None:
    """Определяет смену кредов/состава профилей внешних БД.

    Returns:
        Снимок старого состояния (если креды изменились) либо ``None``.

    """
    global _external_registry_state

    state = _external_registry_state
    if state is None:
        return None
    if state.fingerprint == _external_profiles_fingerprint():
        return None
    _external_registry_state = None
    _build_external_db_registry.cache_clear()
    return state


@lru_cache(maxsize=1)
def _build_db_initializer() -> DatabaseInitializer:
    """Создаёт ``DatabaseInitializer`` main-БД (сырой билдер под ``lru_cache``)."""
    return DatabaseInitializer(settings=settings.database, name="main")


@lru_cache(maxsize=1)
def _build_external_db_registry() -> ExternalDatabaseRegistry:
    """Создаёт реестр внешних БД (сырой билдер под ``lru_cache``)."""
    return ExternalDatabaseRegistry(configs=settings.external_databases.profiles)  # type: ignore[arg-type]  # R2.MYPY: Callable[[],dict]


def get_db_initializer() -> DatabaseInitializer:
    """Lazy singleton ``DatabaseInitializer`` для main-БД (Wave 6.1).

    ADR-0420: синглтон **ротируется** при смене DSN. Если креды в
    настройках изменились (Vault/``.env`` → ``settings.reload()``), старый
    engine закрывается, его кэш сбрасывается, а новый объект создаётся с
    актуальным DSN. Без смены кредов ничего не трогается — тот же engine
    и тот же пул.

    Returns:
        ``DatabaseInitializer`` main-БД с актуальными кредами.

    """
    global _main_db_state

    stale = _detect_main_rotation()
    if stale is not None:
        _schedule_dispose(stale.instance, "main")
        db_logger.info("DSN main-БД изменён — engine пересоздан (ротация кредов)")

    fingerprint = _credential_fingerprint(settings.database)
    instance = _build_db_initializer()
    _main_db_state = _CredentialState(fingerprint=fingerprint, instance=instance)
    if stale is not None:
        _refresh_db_pool_registration(instance)
    return instance


@lru_cache(maxsize=1)
def get_smart_session_manager() -> Any:
    """Lazy singleton :class:`SmartSessionManager` для main-БД (S11 K2 W2).

    Если ``settings.database.replica_dsn`` не задан — manager создаётся
    без replica и работает в single-primary режиме, что эквивалентно
    прежнему поведению ``get_main_session_manager``.

    S145 W3: используем module-level lookup для ``get_db_initializer`` —
    иначе ``monkeypatch.setattr`` в tests/ не сможет подменить функцию
    (импорт binds name в accessors.__dict__, не в database.__dict__).

    ADR-0420: кэш менеджера сбрасывается при ротации кредов — иначе он
    держал бы ``async_sessionmaker`` закрытого engine'а.
    """
    # S145 W3: use module-level lookup для monkeypatch-friendly access.
    # ``from .initializer import get_db_initializer`` binds the name в
    # accessors.__dict__ — ``monkeypatch.setattr(database, ...)`` patches
    # database.__dict__, а не accessors.__dict__. Module-level lookup
    # гарантирует test isolation.
    from src.backend.infrastructure.database import database as _db_mod
    from src.backend.infrastructure.database.smart_session_manager import (
        SmartSessionManager,
    )

    bundle = _db_mod.get_db_initializer().as_bundle()
    return SmartSessionManager(
        primary_sessionmaker=bundle.async_session_maker,
        replica_sessionmaker=bundle.replica_session_maker,
    )


def get_external_db_registry() -> ExternalDatabaseRegistry:
    """Lazy singleton реестра внешних БД (Wave 6.1).

    ADR-0420: реестр пересоздаётся при смене кредов (или состава)
    профилей внешних БД — старые engine'ы закрываются, новые создаются с
    актуальными кредами. Без смены кредов реестр не трогается.

    Returns:
        ``ExternalDatabaseRegistry`` с актуальными кредами профилей.

    """
    global _external_registry_state

    stale = _detect_external_rotation()
    if stale is not None:
        _schedule_dispose(stale.instance, "external")
        db_logger.info("Креды внешних БД изменены — реестр внешних БД пересоздан")

    fingerprint = _external_profiles_fingerprint()
    registry = _build_external_db_registry()
    _external_registry_state = _CredentialState(
        fingerprint=fingerprint, instance=registry
    )
    return registry


def get_db_manager() -> DatabaseInitializer:
    """DB-менеджер main-БД — тот же singleton, что и :func:`get_db_initializer`.

    Cycle 172 (CRITICAL-07): функция **не существовала**, хотя на неё ссылались
    ``core/di/providers/db.py::get_db_manager_provider`` и
    ``DatabaseQueryProcessor``. Итог был такой: ``module.get_db_manager``
    бросал ``AttributeError``, поэтому **каждый** DSL-шаг
    ``db_query`` / ``db_insert`` / ``db_update`` / ``db_upsert`` / ``db_delete``
    падал в ``exchange.fail(...)``. Вся DB-DSL поверхность была мертва.

    Возвращается :class:`DatabaseInitializer`, потому что именно у него есть
    ``get_async_engine()`` — этого и ждёт вызывающий код (и все остальные
    места, которые берут engine напрямую: ``setup_infra/pools.py``,
    ``setup_infra/health.py``, ``processors/storage_ext.py``,
    ``processors/ml_inference.py``).

    Отдельное имя сохранено, потому что оно часть публичной DI-контракта:
    ``get_db_manager_provider()`` возвращает ссылку на этот callable, и тесты
    подменяют его через ``set_db_manager_provider``.
    """
    return get_db_initializer()


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Async context manager, отдающий сессию main-БД.

    Cycle 172 (CRITICAL-10): функции **не существовало**, хотя из неё
    импортировали три resilience-цепочки отказоустойчивости:

    * ``resilience/components/database_chain.py`` — PG → SQLite read-only
      fallback;
    * ``resilience/components/audit_chain.py``;
    * ``resilience/components/mongo_chain.py``.

    Любая из них падала с ``ImportError`` вместо деградации — то есть сам
    механизм failover по БД не работал никогда.

    Сессия коммитится при успешном выходе и откатывается при исключении,
    что соответствует семантике ``DatabaseSessionManager.transaction()``.
    """
    bundle = get_db_initializer().as_bundle()
    session = bundle.async_session_maker()
    try:
        yield session
    except BaseException:
        await session.rollback()
        await session.close()
        raise
    else:
        await session.commit()
        await session.close()


async def apply_db_credential_rotation() -> bool:
    """Пересоздаёт DB-объекты, если изменились DSN (ADR-0420).

    Async-вариант ротации: закрытие старых пулов **ожидается**, а не
    планируется фоновой задачей. Используется наблюдателем конфигурации
    (hot-reload) после ``settings.reload()`` (ADR-0372/0379).

    Returns:
        ``True`` — креды изменились, пулы пересозданы; ``False`` — изменений
        не было (ничего не трогаем).

    """
    rotated = False

    stale = _detect_main_rotation()
    if stale is not None:
        await _dispose_awaitable(_dispose_callable(stale.instance))
        db_logger.info("DSN main-БД изменён — engine пересоздан (ротация кредов)")
        rotated = True

    stale_external = _detect_external_rotation()
    if stale_external is not None:
        await _dispose_awaitable(_dispose_callable(stale_external.instance))
        db_logger.info("Креды внешних БД изменены — реестр внешних БД пересоздан")
        rotated = True

    if rotated:
        _refresh_db_pool_registration(get_db_initializer())

    return rotated


def register_db_credential_rotation_callback(reloader: ConfigHotReloader) -> None:
    """Регистрирует callback ротации кредов БД в hot-reloader'е (ADR-0420).

    Вызывается composition-root'ом рядом с ``register_settings_reload_callback``
    (``plugins/composition/setup_infra/lifecycle.py``): после перезагрузки
    настроек observer'ом вызывается :func:`apply_db_credential_rotation`.

    Args:
        reloader: Hot-reloader конфигурации.

    Returns:
        None.

    """

    async def _rotate_db_credentials() -> None:
        """Ротирует креды БД, если DSN изменился после reload'а настроек."""
        await apply_db_credential_rotation()

    reloader.on_reload(_rotate_db_credentials)


def _reset_db_initializer_cache() -> None:
    """Сбрасывает кэш accessor'а main-БД вместе со снимком кредов."""
    global _main_db_state

    _main_db_state = None
    _build_db_initializer.cache_clear()


def _reset_external_registry_cache() -> None:
    """Сбрасывает кэш accessor'а реестра внешних БД вместе со снимком кредов."""
    global _external_registry_state

    _external_registry_state = None
    _build_external_db_registry.cache_clear()


# Исторический API: ``get_db_initializer.cache_clear()`` /
# ``get_external_db_registry.cache_clear()`` используется в тестах и в
# ``core/di/providers``. Публичная функция-обёртка больше не является
# ``lru_cache``-объектом, поэтому ``cache_clear`` монтируется вручную.
get_db_initializer.cache_clear = _reset_db_initializer_cache  # type: ignore[attr-defined]
get_external_db_registry.cache_clear = _reset_external_registry_cache  # type: ignore[attr-defined]


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat импортов (Wave 6.1)."""
    if name == "db_initializer":
        return get_db_initializer()
    if name == "external_db_registry":
        return get_external_db_registry()
    if name == "get_db_manager":
        return get_db_manager
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
