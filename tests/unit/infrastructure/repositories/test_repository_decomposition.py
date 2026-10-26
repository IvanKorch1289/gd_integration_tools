"""Тесты Wave 4 — декомпозиция ``SQLAlchemyRepository`` и контракты.

Cycle 172, Wave 4.

Крывает:

* **CRITICAL-13** (найден при разборе Wave 4, отсутствовал в отчёте
  аудита): декоратор ``connection()`` всегда подставлял свою сессию
  поверх переданной вызывающим, из-за чего ``get_all_versions``,
  ``get_latest_version`` и ``restore_to_version`` падали с
  ``TypeError: got multiple values for keyword argument 'session'`` —
  весь versioning-контур репозитория был неработоспособен;

* **MEDIUM-13** — декомпозиция God-object'а: ``SQLAlchemyRepository``
  разбит на ``CRUDMixin`` / ``VersioningMixin`` / ``RepositoryHelper``,
  при этом публичное имя класса и вложенный атрибут
  ``SQLAlchemyRepository.HelperMethods`` сохранены (наследуется
  ``OrderRepository``);

* **Wave 4.1 / 4.2** — ``RepositoryProtocol`` и
  ``ExternalSessionManagerProtocol`` объявляют реально используемую
  поверхность.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import String
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, configure_mappers, mapped_column

pytest.importorskip("aiosqlite")

from src.backend.core.domain.models.base import BaseModel  # noqa: E402
from src.backend.infrastructure.database.session_manager import (  # noqa: E402
    main_session_manager,
)
from src.backend.infrastructure.repositories.base import (  # noqa: E402
    SQLAlchemyRepository,
)


class _Wave4Item(BaseModel):
    """Минимальная модель для проверки декомпозиции репозитория."""

    __tablename__ = "test_wave4_items"
    name: Mapped[str] = mapped_column(String, nullable=False)
    value: Mapped[int | None] = mapped_column(default=None)


configure_mappers()

_TEST_TABLES = [
    BaseModel.metadata.tables["test_wave4_items"],
    BaseModel.metadata.tables["test_wave4_items_version"],
    BaseModel.metadata.tables["transaction"],
    BaseModel.metadata.tables["activity"],
]


@pytest_asyncio.fixture
async def repo() -> AsyncIterator[SQLAlchemyRepository[_Wave4Item]]:
    """In-memory SQLite + ``SQLAlchemyRepository`` с подменённым session_maker."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn, tables=_TEST_TABLES
            )
        )

    factory = async_sessionmaker(engine, expire_on_commit=False)
    original_sm = main_session_manager.session_maker
    main_session_manager.session_maker = factory

    try:
        yield SQLAlchemyRepository(_Wave4Item)
    finally:
        main_session_manager.session_maker = original_sm
        await engine.dispose()


# ── CRITICAL-13: versioning-контур ───────────────────────────────────────


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_all_versions_works(
    repo: SQLAlchemyRepository[_Wave4Item],
) -> None:
    """``get_all_versions`` отдаёт версии объекта.

    Раньше метод падал с ``TypeError: got multiple values for keyword
    argument 'session'`` — декоратор ``connection()`` подставлял свою
    сессию поверх переданной вызывающим.
    """
    created = await repo.add(data={"name": "alpha", "value": 1})

    versions = await repo.get_all_versions(object_id=created.id)

    assert versions is not None
    assert len(versions) >= 1


@pytest.mark.unit
@pytest.mark.asyncio
async def test_get_latest_version_works(
    repo: SQLAlchemyRepository[_Wave4Item],
) -> None:
    """``get_latest_version`` отдаёт последнюю версию объекта.

    Раньше — тот же ``TypeError``, что и в ``get_all_versions``.
    """
    created = await repo.add(data={"name": "alpha", "value": 1})

    latest = await repo.get_latest_version(object_id=created.id)

    assert latest is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_restore_to_version_works(
    repo: SQLAlchemyRepository[_Wave4Item],
) -> None:
    """``restore_to_version`` восстанавливает объект до указанной версии.

    Раньше падал с ``TypeError`` — внутри он вызывает ``self.update(...)``,
    который тоже декорирован ``connection()``.
    """
    created = await repo.add(data={"name": "alpha", "value": 1})
    await repo.update(key="id", value=created.id, data={"value": 2})

    versions = await repo.get_all_versions(object_id=created.id)
    assert versions

    first_transaction_id = versions[0].transaction_id

    restored = await repo.restore_to_version(
        object_id=created.id, transaction_id=first_transaction_id
    )

    assert restored is not None


@pytest.mark.unit
@pytest.mark.asyncio
async def test_explicit_session_is_respected() -> None:
    """Явно переданная сессия используется как есть, без двойного ``session=``.

    Это регрессия на сам корень CRITICAL-13: декоратор обязан принять
    сессию от вызывающего, а не подставлять вторую.
    """
    from sqlalchemy.ext.asyncio import AsyncSession

    manager = main_session_manager
    seen: list[AsyncSession] = []

    class _Probe:
        @manager.connection(commit=False)
        async def run(self, session: AsyncSession, marker: str) -> str:
            seen.append(session)
            return marker

    probe = _Probe()
    sentinel = object()

    # Подменяем session_maker так, чтобы декоратор точно не мог подсунуть
    # свою сессию: если бы он это сделал, ``seen`` содержал бы не sentinel.
    original_sm = manager.session_maker

    def _fake_maker() -> AsyncSession:
        raise AssertionError(
            "декоратор не должен открывать свою сессию, когда она передана явно"
        )

    manager.session_maker = _fake_maker  # type: ignore[assignment]
    try:
        result = await probe.run(session=sentinel, marker="ok")  # type: ignore[arg-type]
    finally:
        manager.session_maker = original_sm

    assert result == "ok"
    assert seen == [sentinel]


# ── MEDIUM-13: декомпозиция God-object'а ────────────────────────────────


def test_public_name_preserved() -> None:
    """``SQLAlchemyRepository`` остаётся публичным именем класса."""
    from src.backend.infrastructure.repositories.base.sqlalchemy import (
        SQLAlchemyRepository as Direct,
    )

    assert SQLAlchemyRepository is Direct
    assert SQLAlchemyRepository.__name__ == "SQLAlchemyRepository"


def test_helper_methods_alias_preserved() -> None:
    """``SQLAlchemyRepository.HelperMethods`` доступен (его наследует OrderRepository)."""
    from src.backend.infrastructure.repositories.base.helpers import RepositoryHelper

    assert SQLAlchemyRepository.HelperMethods is RepositoryHelper
    assert hasattr(SQLAlchemyRepository.HelperMethods, "_prepare_and_save_object")


def test_mixins_compose_the_repository() -> None:
    """Репозиторий собран из миксинов, а не из одного монолита."""
    from src.backend.infrastructure.repositories.base.crud_mixin import CRUDMixin
    from src.backend.infrastructure.repositories.base.versioning_mixin import (
        VersioningMixin,
    )

    assert issubclass(SQLAlchemyRepository, CRUDMixin)
    assert issubclass(SQLAlchemyRepository, VersioningMixin)

    # CRUD и versioning лежат в разных модулях — God-object разбит.
    assert CRUDMixin.__module__.endswith("crud_mixin")
    assert VersioningMixin.__module__.endswith("versioning_mixin")


def test_all_public_methods_available() -> None:
    """Все 11 публичных методов репозитория по-прежнему доступны."""
    for name in (
        "get",
        "get_paginated",
        "count",
        "first_or_last",
        "add",
        "bulk_create",
        "update",
        "delete",
        "get_all_versions",
        "get_latest_version",
        "restore_to_version",
    ):
        assert callable(getattr(SQLAlchemyRepository, name, None)), (
            f"метод {name} должен оставаться доступным"
        )


def test_no_abstract_methods_left() -> None:
    """Конкретный репозиторий не имеет незакрытых абстрактных методов."""
    assert not getattr(SQLAlchemyRepository, "__abstractmethods__", frozenset())


# ── Wave 4.1 / 4.2: протоколы ───────────────────────────────────────────


def test_repository_protocol_declares_used_methods() -> None:
    """``RepositoryProtocol`` объявляет реально используемые методы.

    Раньше в протоколе не было ``get_paginated``, ``count`` и
    ``bulk_create``, хотя ``services/core/base/crud_mixin.py`` вызывает
    ``self.repo.get_paginated(...)``.
    """
    from src.backend.core.interfaces.repositories import RepositoryProtocol

    for name in ("get_paginated", "count", "bulk_create"):
        assert hasattr(RepositoryProtocol, name), (
            f"RepositoryProtocol должен объявлять {name}"
        )


def test_external_session_manager_protocol_declares_used_methods() -> None:
    """``ExternalSessionManagerProtocol`` объявляет весь используемый API.

    Раньше был объявлен только ``create_session()``, хотя реализация даёт
    ещё ``transaction`` / ``connection`` / ``get_session``.
    """
    from src.backend.core.interfaces.integrations import ExternalSessionManagerProtocol

    for name in (
        "create_session",
        "transaction",
        "connection",
        "get_session",
        "get_transaction_session",
    ):
        assert hasattr(ExternalSessionManagerProtocol, name), (
            f"ExternalSessionManagerProtocol должен объявлять {name}"
        )


def test_session_manager_satisfies_protocol() -> None:
    """Реализация менеджера сессий удовлетворяет протоколу."""
    from src.backend.core.interfaces.integrations import ExternalSessionManagerProtocol
    from src.backend.infrastructure.database.session_manager import (
        DatabaseSessionManager,
    )

    assert isinstance(main_session_manager, ExternalSessionManagerProtocol)
    assert DatabaseSessionManager is not None
