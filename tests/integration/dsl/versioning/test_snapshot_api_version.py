"""W25.3 — Integration: модель DslSnapshot принимает api_version.

Smoke-тест на SQLite (через testcontainers Postgres skipped если не доступен):
проверяет, что после добавления колонки можно создать запись со
значением api_version и считать его обратно.
"""

# ruff: noqa: S101

from __future__ import annotations

import pytest

pytest_plugins: list[str] = []


@pytest.mark.asyncio
async def test_dsl_snapshot_round_trip_with_api_version() -> None:
    """Создание/чтение DslSnapshot с api_version='v2' через in-memory SQLite."""
    try:
        from sqlalchemy.ext.asyncio import (  # noqa: PLC0415
            AsyncSession,
            async_sessionmaker,
            create_async_engine,
        )
    except ImportError:
        pytest.skip("sqlalchemy[asyncio] не установлен")

    try:
        import aiosqlite  # noqa: F401, PLC0415
    except ImportError:
        pytest.skip("aiosqlite не установлен (extra dev-light)")

    from src.infrastructure.database.models.base import BaseModel
    from src.infrastructure.database.models.dsl_snapshot import DslSnapshot

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", future=True)
    async with engine.begin() as conn:
        await conn.run_sync(BaseModel.metadata.create_all)

    SessionLocal = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with SessionLocal() as session:
        snap = DslSnapshot(
            route_id="rt.versioning",
            version=1,
            spec={"processors": []},
            api_version="v2",
        )
        session.add(snap)
        await session.commit()

        from sqlalchemy import select

        row = (
            await session.execute(
                select(DslSnapshot).where(DslSnapshot.route_id == "rt.versioning")
            )
        ).scalar_one()
        assert row.api_version == "v2"
        assert row.spec == {"processors": []}

    await engine.dispose()
