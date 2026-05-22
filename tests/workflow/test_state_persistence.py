"""Sprint 21 W8 — WorkflowState persistence tests (B-05 closure + S17 K-OPS-1).

Покрытие (4 crash-recover сценария):
    1. Saga checkpoint persists после step N → restore on retry → продолжает с N+1.
    2. Saga compensating after failure on step 3 → 3 compensating_actions persisted.
    3. signal_event переход running → compensating → rolled_back.
    4. Integrity: workflow_id + run_id уникальность + tenant_id присутствует.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import StaticPool
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from src.backend.infrastructure.database.models.base import mapper_registry
from src.backend.infrastructure.workflow.saga_state import (
    WorkflowState,
    WorkflowStateRepository,
)

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """In-memory SQLite session с workflow_state table.

    Используем StaticPool для shared connection между async-вызовами.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        # Создаём только нужные таблицы — workflow_state из metadata
        from sqlalchemy import MetaData

        target = mapper_registry.metadata.tables["workflow_state"]
        single = MetaData()
        target.tometadata(single)
        await conn.run_sync(single.create_all)

    factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.fixture
def wf_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def repo(session: AsyncSession) -> WorkflowStateRepository:
    return WorkflowStateRepository(session)


async def test_checkpoint_persists_and_restores(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Scenario 1: checkpoint after step N → restore returns N+1 start point."""
    await repo.save(workflow_id=wf_id, run_id="r1", step_index=3, tenant_id="t1")
    await session.commit()
    loaded = await repo.load(wf_id, "r1")
    assert loaded is not None
    assert loaded.step_index == 3
    assert loaded.state == "running"
    # Update step_index → upsert
    await repo.save(workflow_id=wf_id, run_id="r1", step_index=4, tenant_id="t1")
    await session.commit()
    after = await repo.load(wf_id, "r1")
    assert after is not None
    assert after.step_index == 4


async def test_compensating_actions_persisted(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Scenario 2: failure на step 3 → 3 compensating_actions persisted."""
    actions = [
        {"step": 1, "action": "reverse_payment"},
        {"step": 2, "action": "release_reservation"},
        {"step": 3, "action": "refund_customer"},
    ]
    await repo.save(
        workflow_id=wf_id,
        run_id="r1",
        step_index=3,
        compensating_actions=actions,
        state="compensating",
        tenant_id="t1",
    )
    await session.commit()
    loaded = await repo.load(wf_id, "r1")
    assert loaded is not None
    assert loaded.state == "compensating"
    assert loaded.compensating_actions == actions
    assert len(loaded.compensating_actions) == 3


async def test_signal_event_transitions(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Scenario 3: running → compensating → rolled_back через signal_event."""
    await repo.save(workflow_id=wf_id, run_id="r1", step_index=1, tenant_id="t1")
    await session.commit()
    assert (await repo.load(wf_id, "r1")).state == "running"

    await repo.signal_event(wf_id, "r1", event="compensating")
    await session.commit()
    assert (await repo.load(wf_id, "r1")).state == "compensating"

    await repo.signal_event(wf_id, "r1", event="rolled_back")
    await session.commit()
    assert (await repo.load(wf_id, "r1")).state == "rolled_back"


async def test_workflow_run_unique_constraint(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Scenario 4: (workflow_id, run_id) uniqueness — повторный save upserts."""
    record_first = await repo.save(
        workflow_id=wf_id, run_id="r1", step_index=1, tenant_id="t1"
    )
    await session.commit()
    record_second = await repo.save(
        workflow_id=wf_id, run_id="r1", step_index=5, tenant_id="t1"
    )
    await session.commit()
    # Тот же id (upsert)
    assert record_first.id == record_second.id
    assert record_second.step_index == 5


async def test_separate_runs_independent(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Один workflow_id может иметь 2 run_id (после retry)."""
    await repo.save(workflow_id=wf_id, run_id="r1", step_index=3, tenant_id="t1")
    await repo.save(workflow_id=wf_id, run_id="r2", step_index=1, tenant_id="t1")
    await session.commit()
    r1 = await repo.load(wf_id, "r1")
    r2 = await repo.load(wf_id, "r2")
    assert r1.step_index == 3
    assert r2.step_index == 1
    assert r1.id != r2.id


async def test_list_compensating(
    repo: WorkflowStateRepository,
    session: AsyncSession,
) -> None:
    """list_compensating возвращает только state='compensating'."""
    wf_a = uuid.uuid4()
    wf_b = uuid.uuid4()
    wf_c = uuid.uuid4()
    await repo.save(
        workflow_id=wf_a, run_id="r", step_index=1, state="running", tenant_id="t1"
    )
    await repo.save(
        workflow_id=wf_b,
        run_id="r",
        step_index=2,
        state="compensating",
        tenant_id="t1",
    )
    await repo.save(
        workflow_id=wf_c,
        run_id="r",
        step_index=3,
        state="compensating",
        tenant_id="t2",
    )
    await session.commit()

    all_comp = await repo.list_compensating()
    assert len(all_comp) == 2
    t1_only = await repo.list_compensating(tenant_id="t1")
    assert len(t1_only) == 1
    assert t1_only[0].workflow_id == wf_b


async def test_signal_event_missing_record_returns_none(
    repo: WorkflowStateRepository,
) -> None:
    """signal_event на отсутствующий record возвращает None (без raise)."""
    result = await repo.signal_event(uuid.uuid4(), "r1", event="compensating")
    assert result is None


async def test_tenant_id_default(
    repo: WorkflowStateRepository,
    session: AsyncSession,
    wf_id: uuid.UUID,
) -> None:
    """Default tenant_id = 'default'."""
    await repo.save(workflow_id=wf_id, run_id="r1", step_index=1)
    await session.commit()
    record = await repo.load(wf_id, "r1")
    assert record.tenant_id == "default"
