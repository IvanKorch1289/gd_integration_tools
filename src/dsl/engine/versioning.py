"""Pipeline Versioning — снэпшоты маршрутов в PostgreSQL (Wave 1.4).

Сохраняет определение маршрута при каждом изменении: позволяет получить
историю версий, сравнить две версии и откатиться на предыдущую.

Хранение перенесено из Redis в таблицу ``dsl_snapshots`` PostgreSQL —
снэпшоты долгоживущие и должны переживать рестарт/eviction. См.
``.claude/REDIS_AUDIT.md``.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, select

from src.infrastructure.database.models.dsl_snapshot import DslSnapshot
from src.infrastructure.database.session_manager import main_session_manager

__all__ = ("PipelineVersionManager", "PipelineSnapshot", "get_pipeline_version_manager")

logger = logging.getLogger("dsl.versioning")


@dataclass(slots=True)
class PipelineSnapshot:
    """Снэпшот маршрута."""

    route_id: str
    version: int
    processors: list[dict[str, Any]]
    feature_flag: str | None
    source: str | None
    description: str | None
    created_at: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "version": self.version,
            "processors": self.processors,
            "feature_flag": self.feature_flag,
            "source": self.source,
            "description": self.description,
            "created_at": self.created_at,
        }


class PipelineVersionManager:
    """Менеджер версий маршрутов поверх PostgreSQL."""

    def _serialize_pipeline(self, pipeline: Any) -> list[dict[str, Any]]:
        """Сериализует processor chain в JSON-совместимый формат."""
        return [
            {"type": type(proc).__name__, "name": proc.name}
            for proc in pipeline.processors
        ]

    async def _next_version(self, route_id: str) -> int:
        """Возвращает следующий номер версии для ``route_id``."""
        async with main_session_manager.create_session() as session:
            stmt = (
                select(DslSnapshot.version)
                .where(DslSnapshot.route_id == route_id)
                .order_by(desc(DslSnapshot.version))
                .limit(1)
            )
            current = (await session.execute(stmt)).scalar_one_or_none()
        return (current or 0) + 1

    async def snapshot(self, pipeline: Any) -> PipelineSnapshot:
        """Создаёт снэпшот маршрута и сохраняет в PostgreSQL."""
        route_id = pipeline.route_id
        version = await self._next_version(route_id)
        processors = self._serialize_pipeline(pipeline)
        snap = PipelineSnapshot(
            route_id=route_id,
            version=version,
            processors=processors,
            feature_flag=pipeline.feature_flag,
            source=pipeline.source,
            description=pipeline.description,
            created_at=time.time(),
        )

        try:
            async with main_session_manager.create_session() as session:
                async with main_session_manager.transaction(session):
                    session.add(
                        DslSnapshot(
                            route_id=route_id,
                            version=version,
                            spec={"processors": processors},
                            feature_flag=snap.feature_flag,
                            source=snap.source,
                            description=snap.description,
                        )
                    )
            logger.info(
                "Pipeline snapshot: %s v%d (%d processors)",
                route_id,
                version,
                len(processors),
            )
        except Exception as exc:
            logger.warning("Snapshot save failed: %s", exc)

        return snap

    async def get_history(self, route_id: str) -> list[dict[str, Any]]:
        """Возвращает историю версий маршрута (asc)."""
        try:
            async with main_session_manager.create_session() as session:
                stmt = (
                    select(DslSnapshot)
                    .where(DslSnapshot.route_id == route_id)
                    .order_by(DslSnapshot.version.asc())
                )
                rows = (await session.execute(stmt)).scalars().all()
            return [
                {
                    "route_id": row.route_id,
                    "version": row.version,
                    "processors": (row.spec or {}).get("processors", []),
                    "feature_flag": row.feature_flag,
                    "source": row.source,
                    "description": row.description,
                    "created_at": row.created_at.timestamp() if row.created_at else 0.0,
                }
                for row in rows
            ]
        except Exception as exc:
            logger.error("History fetch failed: %s", exc)
            return []

    async def compare(self, route_id: str, v1: int, v2: int) -> dict[str, Any]:
        """Сравнивает две версии маршрута."""
        try:
            async with main_session_manager.create_session() as session:
                stmt = select(DslSnapshot).where(
                    DslSnapshot.route_id == route_id,
                    DslSnapshot.version.in_([v1, v2]),
                )
                rows = (await session.execute(stmt)).scalars().all()
            by_ver = {row.version: row for row in rows}
            if v1 not in by_ver or v2 not in by_ver:
                return {"error": "Version not found"}
            snap1 = by_ver[v1].spec or {}
            snap2 = by_ver[v2].spec or {}
            procs1 = {p["name"]: p["type"] for p in snap1.get("processors", [])}
            procs2 = {p["name"]: p["type"] for p in snap2.get("processors", [])}
            added = [k for k in procs2 if k not in procs1]
            removed = [k for k in procs1 if k not in procs2]
            changed = [k for k in procs1 if k in procs2 and procs1[k] != procs2[k]]
            return {
                "route_id": route_id,
                "v1": v1,
                "v2": v2,
                "added_processors": added,
                "removed_processors": removed,
                "changed_processors": changed,
                "feature_flag_changed": by_ver[v1].feature_flag
                != by_ver[v2].feature_flag,
            }
        except Exception as exc:
            return {"error": str(exc)}


from src.infrastructure.application.di import app_state_singleton  # noqa: E402


@app_state_singleton("pipeline_version_manager", PipelineVersionManager)
def get_pipeline_version_manager() -> PipelineVersionManager:
    """Возвращает PipelineVersionManager из app.state или lazy-init fallback."""
