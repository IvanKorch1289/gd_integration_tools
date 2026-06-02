"""Тесты SQL-репозитория rule-engine (Wave [wave:s8/k3-rule-engine-finale]).

Поднимают SQLite in-memory (aiosqlite), создают таблицу
``rule_engine_rulesets`` через ORM-метаданные и проверяют upsert / get /
list_active / delete.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

pytest.importorskip("aiosqlite")

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.backend.core.interfaces.rule_engine import RulesetDoc
from src.backend.infrastructure.database.models.rule_engine import (
    RuleEngineBase,
    RuleEngineRulesetORM,
)
from src.backend.infrastructure.repositories.rule_engine_repository import (
    SQLRuleEngineRepository,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """SQLite in-memory сессия с накатанной таблицей."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(RuleEngineBase.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as sess:
        yield sess
    await engine.dispose()


async def test_upsert_creates_new_record(session: AsyncSession) -> None:
    """Upsert новой записи проставляет id и возвращает RulesetDoc."""
    repo = SQLRuleEngineRepository(session)
    doc = RulesetDoc(name="credit_scoring", version="1", yaml_body="rules: []")

    saved = await repo.upsert(doc)
    await session.commit()

    assert saved.id is not None
    assert saved.name == "credit_scoring"
    assert saved.yaml_body == "rules: []"


async def test_upsert_updates_existing_record(session: AsyncSession) -> None:
    """Повторный upsert по ``(name, version, tenant)`` обновляет yaml_body."""
    repo = SQLRuleEngineRepository(session)
    await repo.upsert(
        RulesetDoc(name="credit_scoring", version="1", yaml_body="v1")
    )
    await session.commit()

    updated = await repo.upsert(
        RulesetDoc(name="credit_scoring", version="1", yaml_body="v1-updated")
    )
    await session.commit()

    assert updated.yaml_body == "v1-updated"
    fetched = await repo.get("credit_scoring", version="1")
    assert fetched is not None
    assert fetched.yaml_body == "v1-updated"


async def test_get_returns_latest_version_when_unspecified(
    session: AsyncSession,
) -> None:
    """Без указания version возвращается запись с максимальной version."""
    repo = SQLRuleEngineRepository(session)
    await repo.upsert(RulesetDoc(name="rs", version="1", yaml_body="v1"))
    await repo.upsert(RulesetDoc(name="rs", version="2", yaml_body="v2"))
    await session.commit()

    latest = await repo.get("rs")

    assert latest is not None
    assert latest.version == "2"
    assert latest.yaml_body == "v2"


async def test_get_filters_by_tenant_scope(session: AsyncSession) -> None:
    """tenant_id None vs значение различают записи."""
    repo = SQLRuleEngineRepository(session)
    await repo.upsert(
        RulesetDoc(name="rs", version="1", yaml_body="global", tenant_id=None)
    )
    await repo.upsert(
        RulesetDoc(name="rs", version="1", yaml_body="acme", tenant_id="acme")
    )
    await session.commit()

    glob = await repo.get("rs")
    acme = await repo.get("rs", tenant_id="acme")

    assert glob is not None and glob.yaml_body == "global"
    assert acme is not None and acme.yaml_body == "acme"


async def test_list_active_skips_disabled(session: AsyncSession) -> None:
    """list_active игнорирует enabled=False."""
    repo = SQLRuleEngineRepository(session)
    await repo.upsert(
        RulesetDoc(name="active", version="1", yaml_body="x", enabled=True)
    )
    await repo.upsert(
        RulesetDoc(name="disabled", version="1", yaml_body="y", enabled=False)
    )
    await session.commit()

    items = await repo.list_active()

    names = {d.name for d in items}
    assert "active" in names
    assert "disabled" not in names


async def test_delete_removes_record(session: AsyncSession) -> None:
    """delete возвращает True при успехе и False при отсутствии."""
    repo = SQLRuleEngineRepository(session)
    await repo.upsert(RulesetDoc(name="rs", version="1", yaml_body="x"))
    await session.commit()

    removed = await repo.delete("rs", "1")
    await session.commit()
    not_found = await repo.delete("rs", "1")

    assert removed is True
    assert not_found is False
    assert await repo.get("rs", version="1") is None
