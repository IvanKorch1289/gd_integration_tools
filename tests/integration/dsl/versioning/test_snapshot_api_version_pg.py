"""W25.3 / pre-W26 — DslSnapshot round-trip на реальном PostgreSQL.

Использует фикстуру ``pg_engine_with_alembic`` (testcontainers + alembic upgrade head),
чтобы убедиться, что api_version-колонка реально создаётся миграцией и принимает
значения в production-схеме.

Маркер ``requires_pg`` позволяет отфильтровать тест в среде без Docker.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.requires_pg


@pytest.mark.asyncio
async def test_dsl_snapshot_round_trip_with_api_version_pg(
    pg_engine_with_alembic: "AsyncEngine",
) -> None:
    """Создание/чтение DslSnapshot с api_version='v2' через реальный Postgres."""
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from src.backend.infrastructure.database.models.dsl_snapshot import DslSnapshot

    SessionLocal = async_sessionmaker(
        pg_engine_with_alembic, class_=AsyncSession, expire_on_commit=False
    )

    async with SessionLocal() as session:
        snap = DslSnapshot(
            route_id="rt.versioning.pg",
            version=1,
            spec={"processors": []},
            api_version="v2",
        )
        session.add(snap)
        await session.commit()

        row = (
            await session.execute(
                select(DslSnapshot).where(
                    DslSnapshot.route_id == "rt.versioning.pg"
                )
            )
        ).scalar_one()
        assert row.api_version == "v2"
        assert row.spec == {"processors": []}

        await session.delete(row)
        await session.commit()
