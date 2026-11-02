from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from functools import lru_cache, wraps
from typing import ParamSpec, TypeVar

from sqlalchemy.exc import IntegrityError, InterfaceError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.ext.asyncio.session import AsyncSessionTransaction

from src.backend.core.config.settings import settings
from src.backend.core.errors import DatabaseError, NotFoundError
from src.backend.core.logging import get_logger
from src.backend.core.resilience.breaker import BreakerSpec, get_breaker_registry
from src.backend.core.resilience.retry import retry_async
from src.backend.core.tenancy.sqlalchemy_filter import (
    apply_tenant_filter,
    register_external_engine,
)

# Cycle 172 (Wave 4.3): ``get_external_db_registry`` импортируется
# напрямую, поэтому ``patch("...session_manager.get_external_db_registry")``
# в тестах бьёт по **другому** объекту модуля, если ``sys.modules`` был
# перезаполнен (outbox-тесты подменяют session_manager заглушкой, а
# ``tests/unit/conftest.py`` вычищает её на ``pytest_collectstart``).
# В итоге патч не срабатывал, и тест падал на реальном
# ``settings.external_databases.profiles`` — который требует
# EXT_DB_<PROFILE>_USERNAME в env.
#
# Решение — тот же module-level lookup, что в ``accessors.py`` (S145 W3):
# обращаемся к атрибуту пакета в момент вызова, а не к локальной ссылке.
# Тест тогда может подменить пакетный экспорт, и он гарантированно
# подхватится независимо от того, какой объект модуля лежит в sys.modules.
from src.backend.infrastructure.database import database as _database_pkg
from src.backend.infrastructure.database.database import get_db_initializer
from src.backend.infrastructure.database.listeners import (
    sanitize_db_error_text,
    sanitized_exc_info,
)

db_logger = get_logger("database")

breaker_registry = get_breaker_registry()

__all__ = (
    "RETRYABLE_PG_CODES",
    "DatabaseSessionManager",
    "RetryableTransactionError",
    "get_external_session_manager",
    "get_main_session_manager",
    "get_smart_read_session",
    "get_smart_write_session",
    "is_retryable_transaction_error",
    "main_session_manager",
    "pg_sqlstate",
)


P = ParamSpec("P")
R = TypeVar("R")

#: Ошибки, при которых повторное установление соединения осмысленно.
#: Cycle 172 (MEDIUM-10): ``max_retries`` был объявлен в конфиге, но не
#: читался ни одним читателем в DB-слое — настройка была мёртвой.
#:
#: Повтор делается **только** на этапе установления соединения. Тело
#: транзакции не переигрывается намеренно: оно не идемпотентно, и повтор
#: после частичной записи способен продублировать данные. Именно поэтому в
#: retryable-попадают только ``OperationalError``/``InterfaceError`` —
#: драйвер сообщает о недоступности соединения, а не о логической ошибке.
_RETRYABLE_CONNECT_ERRORS: tuple[type[BaseException], ...] = (
    OperationalError,
    InterfaceError,
)

#: SQLSTATE-коды PostgreSQL, при которых повтор транзакции осмысленен
#: (ADR-0418): ``40001`` — ``serialization_failure``, ``40P01`` —
#: ``deadlock_detected``.
#:
#: Раньше повтор делался только на этапе установления соединения и только
#: для ``OperationalError``/``InterfaceError`` — сериализационные конфликты
#: (типичный сценарий двух конкурирующих транзакций) приводили к отказу
#: всей операции без единой попытки повтора.
RETRYABLE_PG_CODES: frozenset[str] = frozenset({"40001", "40P01"})


class RetryableTransactionError(Exception):
    """Внутренний маркер сериализационной ошибки (pgcode 40001/40P01).

    :func:`src.backend.core.resilience.retry.retry_async` умеет повторять
    только по **типу** исключения, а SQLAlchemy оборачивает сериализационную
    ошибку в ``OperationalError`` (вместе с десятком других). Поэтому ошибка
    с распознанным pgcode пере-оборачивается в этот маркер, а исходное
    исключение сохраняется в ``__cause__`` и пробрасывается вызывающему
    после исчерпания попыток.
    """


def pg_sqlstate(exc: BaseException) -> str | None:
    """Извлечь SQLSTATE (pgcode) из исключения драйвера.

    Args:
        exc: Исключение SQLAlchemy или драйвера БД.

    Returns:
        Код SQLSTATE в верхнем регистре либо ``None``, если код не найден.

    """
    for candidate in (exc, getattr(exc, "orig", None)):
        if candidate is None:
            continue
        for attr in ("sqlstate", "pgcode"):
            value = getattr(candidate, attr, None)
            if isinstance(value, str) and value:
                return value.upper()
    return None


def is_retryable_transaction_error(exc: BaseException) -> bool:
    """Сериализационная ошибка / дедлок (pgcode 40001 / 40P01).

    Args:
        exc: Исключение SQLAlchemy или драйвера БД.

    Returns:
        ``True``, если транзакцию осмысленно повторить.

    """
    state = pg_sqlstate(exc)
    return state is not None and state in RETRYABLE_PG_CODES


#: Ошибки, которые НЕ считаются отказом БД (Wave 16 / X4, ADR-0383).
#:
#: ``NotFoundError`` — ожидаемый исход поиска, ``IntegrityError`` —
#: ожидаемый исход записи (дубликат ключа). Раньше они проходили через
#: ``self._breaker.guard()``, и десять «не найдено» подряд открывали
#: breaker ``db:<name>`` на 30 с, глуша весь DB-трафик (воспроизведено:
#: ``OpenedState``). Настоящие отказы (``OperationalError`` и прочие)
#: breaker по-прежнему открывают.
_BREAKER_EXCLUDED_ERRORS: tuple[type[BaseException], ...] = (
    NotFoundError,
    IntegrityError,
)


def _sanitized_integrity_error(exc: IntegrityError) -> IntegrityError:
    """Пересоздать ``IntegrityError`` без значений bind-параметров.

    SQLAlchemy печатает в тексте исключения фактические значения
    параметров (``[parameters: ('ivan@example.com',)]``). Конструктор с
    ``hide_parameters=True`` убирает этот блок, сохраняя SQL и текст
    драйвера — диагностика не теряется, PII не утекает (ADR-0383).

    Args:
        exc: Исходное исключение SQLAlchemy.

    Returns:
        ``IntegrityError`` с очищенным текстом.
    """
    return IntegrityError(
        exc.statement,
        exc.params,
        exc.orig,
        hide_parameters=True,
        code=exc.code,
        ismulti=exc.ismulti,
    )


class DatabaseSessionManager:
    """Менеджер асинхронных сессий SQLAlchemy.

    Используется на сервисном уровне:
    - create_session() для read-only или ручного управления;
    - transaction() для явного commit/rollback;
    - connection() как декоратор сервисных методов.
    """

    def __init__(
        self, session_maker: async_sessionmaker[AsyncSession], db_name: str = "main"
    ):
        self.session_maker = session_maker
        self.db_name = db_name
        self.logger = db_logger
        # S88 W2 (V2 P0 #6 HIGH): wire up tenant auto-filter (was dead code since
        # S21 W0). Listeners реєструються на класі ``Session`` (SessionEvents),
        # тому target аргумент ігнорується. Ідемпотентно через _INSTALLED.
        apply_tenant_filter()
        # ADR-0417: внешние профили БД — отдельный tenant-контур. Tenant-guard
        # (ORM-фильтр + raw-SQL guard) к ним не применяется: иначе запрос к
        # таблице с tenant-именем (``workflow_instances``) отклоняется, и
        # ``db_query_external`` / ``jdbc_query`` / ``batch_*`` не работают.
        if db_name != "main":
            register_external_engine(session_maker)
        # Wave 6.2: per-DB circuit breaker. Параметры из settings.database.*.
        self._breaker = breaker_registry.get_or_create(
            f"db:{db_name}",
            BreakerSpec(
                failure_threshold=settings.database.circuit_breaker_max_failures,
                recovery_timeout=float(settings.database.circuit_breaker_reset_timeout),
                excluded_exceptions=_BREAKER_EXCLUDED_ERRORS,
            ),
        )

    async def _acquire_session(self) -> AsyncSession:
        """Открывает сессию, повторяя попытку при недоступности соединения.

        Cycle 172 (MEDIUM-10): ``max_retries`` был объявлен в конфиге, но не
        читался ни одним читателем в DB-слое — настройка была мёртвой.

        Повтор выполняется через единый API ``core.resilience.retry``
        (tenacity) — R-V15-8 требует консолидировать кастомный retry-код
        поверх tenacity, а не плодить ещё одну реализацию.

        Важно: соединение устанавливается **явно** (``session.connection()``).
        ``async_sessionmaker`` создаёт сессию лениво, реальное соединение
        происходит на первом запросе — то есть уже за пределами retry-области,
        и повтор был бы фиктивным.

        Тело транзакции не переигрывается: оно не идемпотентно.
        """
        max_retries = max(0, int(settings.database.max_retries))

        async def _open() -> AsyncSession:
            session = self.session_maker()
            try:
                await session.connection()
            except BaseException:
                await session.close()
                raise
            return session

        if max_retries == 0:
            return await _open()

        return await retry_async(
            _open,
            max_attempts=max_retries + 1,
            base_delay=0.5,
            max_delay=10.0,
            retryable=_RETRYABLE_CONNECT_ERRORS,
            op=f"db.connect:{self.db_name}",
        )

    @asynccontextmanager
    async def create_session(self) -> AsyncGenerator[AsyncSession]:
        """Создаёт и возвращает асинхронную сессию (под защитой circuit breaker)."""
        async with self._breaker.guard():
            session = await self._acquire_session()
            try:
                yield session
            except NotFoundError:
                # Бизнес-ошибка: не маскируется под DatabaseError и не
                # считается отказом БД (ADR-0383).
                raise
            except IntegrityError as exc:
                # Дубликат ключа — бизнес-ошибка, а не отказ БД: пробрасывается
                # как IntegrityError (исключён из breaker'а), но без PII.
                self.logger.error(
                    "Ошибка целостности данных в БД '%s': %s",
                    self.db_name,
                    sanitize_db_error_text(str(exc)),
                    exc_info=sanitized_exc_info(exc),
                )
                raise _sanitized_integrity_error(exc) from None
            except Exception as exc:
                self.logger.error(
                    "Ошибка при работе с сессией БД '%s': %s",
                    self.db_name,
                    sanitize_db_error_text(str(exc)),
                    exc_info=sanitized_exc_info(exc),
                )
                raise DatabaseError(
                    message=f"Failed to create database session for '{self.db_name}'"
                ) from exc
            finally:
                await session.close()

    @asynccontextmanager
    async def transaction(self, session: AsyncSession) -> AsyncGenerator[None]:
        """Выполняет commit при успехе и rollback при ошибке.

        ADR-0418 (волна 24) — два изменения относительно прежнего
        «yield → commit / rollback всего подряд»:

        * **BEGIN-этап повторяется при сериализационной ошибке.**
          PostgreSQL сообщает о конфликте сериализации (SQLSTATE ``40001``)
          и о дедлоке (``40P01``) — раньше эти ошибки не повторялись
          вовсе, операция падала с первой попытки. Повтор делается
          **только** на этапе открытия транзакции: тело транзакции на
          этом этапе ещё не выполнялось, частичных записей нет, повтор
          безопасен. Backoff — экспоненциальный (tenacity через
          ``core.resilience.retry``);
        * **тело транзакции выполняется под SAVEPOINT.** Ошибка тела
          откатывает savepoint, а не всю транзакцию: внешняя транзакция
          остаётся открытой, и вызывающий может её продолжить
          (например — повторить упавший блок).

        Args:
            session: Открытая async-сессия.

        Yields:
            ``None`` — тело транзакции.

        Raises:
            DatabaseError: При ошибке открытия транзакции или её тела.

        """
        try:
            savepoint = await self._begin_transaction(session)
        except Exception as exc:
            self.logger.error(
                "Ошибка открытия транзакции в БД '%s': %s",
                self.db_name,
                sanitize_db_error_text(str(exc)),
                exc_info=sanitized_exc_info(exc),
            )
            raise DatabaseError(
                message=f"Failed to begin transaction for '{self.db_name}'"
            ) from exc

        try:
            yield
        except Exception as exc:
            # ADR-0418: откат SAVEPOINT — внешняя транзакция не сбрасывается.
            await self._rollback_savepoint(savepoint)
            self.logger.error(
                "Ошибка транзакции в БД '%s': %s",
                self.db_name,
                sanitize_db_error_text(str(exc)),
                exc_info=sanitized_exc_info(exc),
            )
            raise DatabaseError(
                message=f"Transaction failed for '{self.db_name}'"
            ) from exc

        await savepoint.commit()
        await session.commit()

    async def _begin_transaction(
        self, session: AsyncSession
    ) -> AsyncSessionTransaction:
        """Открывает транзакцию и SAVEPOINT на её тело (ADR-0418).

        Повтор делается только на этом этапе: тело транзакции ещё не
        выполнялось, поэтому повтор не может продублировать данные.

        Args:
            session: Открытая async-сессия.

        Returns:
            Транзакция SAVEPOINT, оборачивающая тело.

        Raises:
            Exception: Ошибка установления соединения / BEGIN / SAVEPOINT.

        """
        max_retries = max(0, int(settings.database.max_retries))

        async def _open() -> AsyncSessionTransaction:
            if not session.in_transaction():
                # Явный BEGIN: без него «этап открытия транзакции» —
                # это первое обращение к БД (BEGIN + SAVEPOINT).
                await session.begin()
            # SAVEPOINT на тело транзакции: ошибка тела откатывает
            # savepoint, а не всю транзакцию (ADR-0418).
            return await session.begin_nested()

        if max_retries == 0:
            return await _open()

        async def _attempt() -> AsyncSessionTransaction:
            try:
                return await _open()
            except Exception as exc:
                if not is_retryable_transaction_error(exc):
                    raise
                # Транзакция после сериализационной ошибки невалидна —
                # откатываем, чтобы следующая попытка шла с чистого
                # состояния.
                try:
                    await session.rollback()
                except Exception as rollback_exc:  # noqa: BLE001 — битое соединение
                    self.logger.warning(
                        "Откат транзакции в БД '%s' не удался: %s",
                        self.db_name,
                        sanitize_db_error_text(str(rollback_exc)),
                    )
                raise RetryableTransactionError(
                    f"retryable transaction error (sqlstate={pg_sqlstate(exc)})"
                ) from exc

        try:
            return await retry_async(
                _attempt,
                max_attempts=max_retries + 1,
                base_delay=0.5,
                max_delay=10.0,
                retryable=(RetryableTransactionError,),
                op=f"db.begin:{self.db_name}",
            )
        except RetryableTransactionError as exc:
            # Возвращаем вызывающему исходную ошибку БД, а не маркер.
            cause = exc.__cause__
            raise (cause if cause is not None else exc) from None

    async def _rollback_savepoint(self, savepoint: AsyncSessionTransaction) -> None:
        """Откатить SAVEPOINT, не сбрасывая внешнюю транзакцию (ADR-0418).

        Args:
            savepoint: Транзакция SAVEPOINT тела.

        """
        try:
            await savepoint.rollback()
        except Exception as exc:  # noqa: BLE001 — битое соединение
            self.logger.warning(
                "Откат savepoint в БД '%s' не удался: %s",
                self.db_name,
                sanitize_db_error_text(str(exc)),
            )

    async def get_session(self) -> AsyncGenerator[AsyncSession]:
        """Dependency-совместимый генератор сессии без auto-commit."""
        async with self.create_session() as session:
            yield session

    async def get_transaction_session(self) -> AsyncGenerator[AsyncSession]:
        """Dependency-совместимый генератор транзакционной сессии."""
        async with self.create_session() as session, self.transaction(session):
            yield session

    def connection(
        self, isolation_level: str | None = None, commit: bool = True
    ) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
        """Декоратор сервисного метода.

        Поведение:
        - в метод пробрасывается `session=...`;
        - при ошибке выполняется rollback;
        - при `commit=True` выполняется commit.

        Параметр `isolation_level` сохранён для обратной совместимости.

        Cycle 172 (CRITICAL-13): если вызывающий код **передал** сессию
        явно (``method(session=my_session, ...)``), декоратор использует её
        и не управляет её lifecycle — commit/rollback остаются на вызывающем.

        Раньше декоратор всегда подставлял свою сессию поверх переданной:
        ``method(*args, session=session, **kwargs)`` давало
        ``TypeError: got multiple values for keyword argument 'session'``.
        На этом падали три метода ``SQLAlchemyRepository`` — ``get_all_versions``,
        ``get_latest_version`` (через ``main_class.get(session=...)``) и
        ``restore_to_version`` (через ``self.update(session=...)``).
        То есть весь versioning-контур репозитория был неработоспособен.
        """

        def decorator(method: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
            @wraps(method)
            async def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                # Сессия, переданная вызывающим: используем её as-is.
                provided_session = kwargs.get("session")
                if provided_session is not None:
                    kwargs.pop("session")
                    return await method(*args, session=provided_session, **kwargs)  # type: ignore[arg-type]

                # Cycle 172 (HIGH-11): breaker'а оборачивал только
                # ``create_session()``. Все 11 методов ``SQLAlchemyRepository``
                # идут через этот декоратор, а не через ``create_session()``,
                # поэтому breaker ``db:main`` на основном CRUD-пути не
                # срабатывал **никогда** — фича существовала только на бумаге.
                # Теперь guard стоит на обоих путях.
                async with self._breaker.guard():
                    async with self.session_maker() as session:
                        try:
                            if isolation_level:
                                await session.connection(
                                    execution_options={
                                        "isolation_level": isolation_level
                                    }
                                )

                            result = await method(*args, session=session, **kwargs)  # type: ignore[arg-type]

                            if commit and session.in_transaction():
                                await session.commit()

                            return result

                        except NotFoundError:
                            raise
                        except IntegrityError as exc:
                            # Дубликат ключа — бизнес-ошибка, а не отказ БД:
                            # пробрасывается как IntegrityError (исключён из
                            # breaker'а — ADR-0383), но без значений параметров.
                            if session.in_transaction():
                                await session.rollback()

                            self.logger.error(
                                "Ошибка целостности данных в БД '%s': %s",
                                self.db_name,
                                sanitize_db_error_text(str(exc)),
                                exc_info=sanitized_exc_info(exc),
                            )
                            raise _sanitized_integrity_error(exc) from None
                        except Exception as exc:
                            if session.in_transaction():
                                await session.rollback()

                            self.logger.error(
                                "Ошибка при выполнении транзакции в БД '%s': %s",
                                self.db_name,
                                sanitize_db_error_text(str(exc)),
                                exc_info=sanitized_exc_info(exc),
                            )
                            raise DatabaseError(
                                message=(
                                    f"Ошибка при выполнении транзакции "
                                    f"в БД '{self.db_name}' - "
                                    f"{sanitize_db_error_text(str(exc))}"
                                )
                            ) from exc

            return wrapper

        return decorator


@lru_cache(maxsize=1)
def get_main_session_manager() -> DatabaseSessionManager:
    """Lazy singleton ``DatabaseSessionManager`` для main-БД (Wave 6.1)."""
    return DatabaseSessionManager(
        session_maker=get_db_initializer().async_session_maker, db_name="main"
    )


@lru_cache(maxsize=32)
def get_external_session_manager(profile_name: str) -> DatabaseSessionManager:
    """Возвращает session manager для внешней БД по profile_name.

    Cycle 172 (LOW-03): менеджер создавался заново на **каждый** вызов, тогда
    как основной БД-кэшируется через ``@lru_cache``. Каждый новый экземпляр
    регистрировал собственный breaker ``db:<profile>`` в общем реестре —
    счётчики отказов обнулялись, и breaker не накапливал историю сбоев.
    Теперь внешние менеджеры кэшируются по имени профиля.
    """
    initializer = _database_pkg.get_external_db_registry().get_initializer(profile_name)

    return DatabaseSessionManager(
        session_maker=initializer.async_session_maker, db_name=profile_name
    )


async def get_smart_read_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI Depends-совместимый генератор read-only сессии (S11 K2 W2).

    Использует :class:`SmartSessionManager`: read-запросы идут на
    replica при доступности, иначе fallback на primary.
    """
    from src.backend.infrastructure.database.database import get_smart_session_manager

    manager = get_smart_session_manager()
    async with manager.acquire(mode="read") as session:
        yield session


async def get_smart_write_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI Depends-совместимый генератор write-сессии (S11 K2 W2).

    Write-сессии всегда идут на primary engine; replica для write
    никогда не используется.
    """
    from src.backend.infrastructure.database.database import get_smart_session_manager

    manager = get_smart_session_manager()
    async with manager.acquire(mode="write") as session:
        yield session


def __getattr__(name: str) -> DatabaseSessionManager:
    """Module-level lazy accessor для backward compat ``main_session_manager``.

    Return type narrowed from ``Any`` to :class:`DatabaseSessionManager` (S3.5):
    единственный успешный return-path возвращает ``get_main_session_manager()``,
    все прочие имена приводят к ``AttributeError`` и, следовательно, не имеют
    значения для статической типизации.
    """
    if name == "main_session_manager":
        return get_main_session_manager()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
