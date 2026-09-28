"""Runtime contract tests: LangMem erasure + tenant isolation (ADR-0347).

Эти тесты ЗАПУСКАЮТ адаптер и сервисный слой против настоящих SQLAlchemy-моделей
на in-memory SQLite. До этой волны адаптер erasure не исполнялся ни одним
тестом, а privacy gate проверял только наличие строк-"маркеров" в исходнике —
поэтому нерабочий ``LangMemEpisodic.subject_id`` проходил как "covered".
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from src.backend.core.domain.models.langmem_models import (
    LangMemEpisodic,
    LangMemProcedural,
)
from src.backend.core.privacy.delete_data_subject._langmem import LangMemErasureAdapter
from src.backend.services.ai.memory.langmem.episodic import EpisodicMemory
from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory

pytestmark = pytest.mark.asyncio


@pytest.fixture()
async def session_factory() -> Any:
    """In-memory SQLite с реальными LangMem-моделями."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: LangMemEpisodic.metadata.create_all(sync_conn)
        )
        await conn.run_sync(
            lambda sync_conn: LangMemProcedural.metadata.create_all(sync_conn)
        )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


# --------------------------------------------------------------------------
# Schema contract — the regression that broke erasure
# --------------------------------------------------------------------------


@pytest.mark.asyncio(loop_scope="function")
async def test_models_expose_subject_id_and_tenant() -> None:
    """Модели обязаны иметь subject_id (для erasure) и tenant (для скоупа)."""
    for model in (LangMemEpisodic, LangMemProcedural):
        cols = {c.name for c in model.__table__.columns}
        assert "subject_id" in cols, f"{model.__name__} без subject_id → erasure падает"
        assert "tenant" in cols, f"{model.__name__} без tenant → нет скоупа"


async def test_adapter_builds_delete_queries_without_attribute_error(
    session_factory: Any,
) -> None:
    """Regression: адаптер строил ``LangMemEpisodic.subject_id`` — колонки не было.

    Этот тест падал бы с AttributeError на старом коде.
    """
    from src.backend.core.privacy.delete_data_subject._types import (
        ErasureResultStatus,
        ErasureStrategy,
    )

    adapter = LangMemErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="t-1",
        tenant_id="tenant-a",
    )
    assert result.status is not ErasureResultStatus.FAILED, result.error


# --------------------------------------------------------------------------
# Erasure: tenant A removed, tenant B preserved
# --------------------------------------------------------------------------


async def test_erasure_deletes_subject_in_tenant_and_preserves_other_tenant(
    session_factory: Any,
) -> None:
    """Erasure удаляет данные subject'а в своём тенанте и НЕ трогает чужой."""
    from sqlalchemy import select

    from src.backend.core.privacy.delete_data_subject._types import (
        ErasureResultStatus,
        ErasureStrategy,
    )

    episodic = EpisodicMemory(session_factory)
    # Тот же subject_id в двух тенантах + другой subject в первом.
    await episodic.add(
        session_id="s1",
        role="user",
        content="A-secret",
        tenant="tenant-a",
        subject_id="user:42",
    )
    await episodic.add(
        session_id="s2",
        role="user",
        content="B-secret",
        tenant="tenant-b",
        subject_id="user:42",
    )
    await episodic.add(
        session_id="s3",
        role="user",
        content="A-other",
        tenant="tenant-a",
        subject_id="user:99",
    )

    adapter = LangMemErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:42",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="t-1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.SUCCESS, result.error

    async with session_factory() as session:
        remaining = (
            (
                await session.execute(
                    select(LangMemEpisodic.content).order_by(LangMemEpisodic.content)
                )
            )
            .scalars()
            .all()
        )
    assert remaining == ["A-other", "B-secret"], (
        f"Ожидались только чужие записи, получено {remaining}"
    )


async def test_erasure_is_noop_for_unknown_subject(session_factory: Any) -> None:
    """Erasure неизвестного subject не должен падать и не удалять чужие строки."""
    from sqlalchemy import func, select

    from src.backend.core.privacy.delete_data_subject._types import (
        ErasureResultStatus,
        ErasureStrategy,
    )

    episodic = EpisodicMemory(session_factory)
    await episodic.add(
        session_id="s1",
        role="user",
        content="keep",
        tenant="tenant-a",
        subject_id="user:42",
    )
    adapter = LangMemErasureAdapter(session_factory=session_factory)
    result = await adapter.execute(
        subject_id="user:does-not-exist",
        subject_type="user",
        strategy=ErasureStrategy.HARD_DELETE,
        correlation_id="t-1",
        tenant_id="tenant-a",
    )
    assert result.status is ErasureResultStatus.SUCCESS, result.error
    async with session_factory() as session:
        count = (
            await session.execute(select(func.count()).select_from(LangMemEpisodic))
        ).scalar_one()
    assert count == 1


# --------------------------------------------------------------------------
# Tenant isolation on the read path (cross-tenant read leak)
# --------------------------------------------------------------------------


async def test_recall_returns_only_own_tenant_episodes(session_factory: Any) -> None:
    """Знание чужого session_id не должно давать чтение памяти другого тенанта."""
    episodic = EpisodicMemory(session_factory)
    # Одинаковый session_id у двух тенантов — раньше recall() вернул бы оба.
    await episodic.add(
        session_id="shared",
        role="user",
        content="tenant-a-mem",
        tenant="tenant-a",
        subject_id="user:1",
    )
    await episodic.add(
        session_id="shared",
        role="user",
        content="tenant-b-mem",
        tenant="tenant-b",
        subject_id="user:1",
    )

    rows = await episodic.recall(tenant="tenant-a", session_id="shared")
    assert [r["content"] for r in rows] == ["tenant-a-mem"]


async def test_recall_rejects_empty_tenant(session_factory: Any) -> None:
    """Пустой tenant → ValueError (fail-closed), а не выдача всех строк."""
    episodic = EpisodicMemory(session_factory)
    with pytest.raises(ValueError, match="tenant"):
        await episodic.recall(tenant="", session_id="shared")


async def test_procedural_recall_is_tenant_scoped(session_factory: Any) -> None:
    """Процедуры тоже не должны протекать между тенантами."""
    procedural = ProceduralMemory(session_factory)
    await procedural.add(name="deploy", tenant="tenant-a", subject_id="user:1")
    await procedural.add(name="deploy", tenant="tenant-b", subject_id="user:1")
    rows_a = await procedural.recall(tenant="tenant-a")
    assert len(rows_a) == 1
    with pytest.raises(ValueError, match="tenant"):
        await procedural.recall(tenant="")


async def test_add_rejects_empty_tenant_and_subject(session_factory: Any) -> None:
    """Запись без tenant/subject_id запрещена — fail-closed на записи."""
    episodic = EpisodicMemory(session_factory)
    with pytest.raises(ValueError, match="tenant"):
        await episodic.add(
            session_id="s", role="u", content="c", tenant="", subject_id="user:1"
        )
    with pytest.raises(ValueError, match="subject_id"):
        await episodic.add(
            session_id="s", role="u", content="c", tenant="tenant-a", subject_id=""
        )
