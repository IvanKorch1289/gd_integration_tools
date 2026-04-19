"""Pipeline Versioning — снэпшоты маршрутов.

Сохраняет определения маршрутов при каждом изменении.
Позволяет сравнивать версии, откатываться на предыдущую.

Хранит снэпшоты в Redis (JSON-сериализация processor chain).
"""

import logging
import time
from dataclasses import dataclass
from typing import Any

__all__ = ("PipelineVersionManager", "PipelineSnapshot", "get_pipeline_version_manager")

logger = logging.getLogger("dsl.versioning")

_SNAPSHOT_PREFIX = "dsl_snapshot:"


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
    """Менеджер версий маршрутов."""

    def __init__(self) -> None:
        self._versions: dict[str, int] = {}

    def _serialize_pipeline(self, pipeline: Any) -> list[dict[str, Any]]:
        """Сериализует processor chain в JSON-совместимый формат."""
        result = []
        for proc in pipeline.processors:
            result.append({
                "type": type(proc).__name__,
                "name": proc.name,
            })
        return result

    async def snapshot(self, pipeline: Any) -> PipelineSnapshot:
        """Создаёт снэпшот маршрута и сохраняет в Redis."""
        route_id = pipeline.route_id
        version = self._versions.get(route_id, 0) + 1
        self._versions[route_id] = version

        snap = PipelineSnapshot(
            route_id=route_id,
            version=version,
            processors=self._serialize_pipeline(pipeline),
            feature_flag=pipeline.feature_flag,
            source=pipeline.source,
            description=pipeline.description,
            created_at=time.time(),
        )

        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            key = f"{_SNAPSHOT_PREFIX}{route_id}:v{version}"
            await redis_client._redis.set(key, orjson.dumps(snap.to_dict()))

            latest_key = f"{_SNAPSHOT_PREFIX}{route_id}:latest"
            await redis_client._redis.set(latest_key, orjson.dumps(snap.to_dict()))

            logger.info("Pipeline snapshot: %s v%d (%d processors)", route_id, version, len(snap.processors))
        except Exception as exc:
            logger.warning("Snapshot save failed: %s", exc)

        return snap

    async def get_history(self, route_id: str) -> list[dict[str, Any]]:
        """Возвращает историю версий маршрута."""
        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            result = []
            for v in range(1, self._versions.get(route_id, 0) + 1):
                key = f"{_SNAPSHOT_PREFIX}{route_id}:v{v}"
                raw = await redis_client._redis.get(key)
                if raw:
                    result.append(orjson.loads(raw))
            return result
        except Exception as exc:
            logger.error("History fetch failed: %s", exc)
            return []

    async def compare(self, route_id: str, v1: int, v2: int) -> dict[str, Any]:
        """Сравнивает две версии маршрута."""
        try:
            from app.infrastructure.clients.redis import redis_client
            import orjson

            raw1 = await redis_client._redis.get(f"{_SNAPSHOT_PREFIX}{route_id}:v{v1}")
            raw2 = await redis_client._redis.get(f"{_SNAPSHOT_PREFIX}{route_id}:v{v2}")

            if not raw1 or not raw2:
                return {"error": "Version not found"}

            snap1 = orjson.loads(raw1)
            snap2 = orjson.loads(raw2)

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
                "feature_flag_changed": snap1.get("feature_flag") != snap2.get("feature_flag"),
            }
        except Exception as exc:
            return {"error": str(exc)}


from app.core.di import app_state_singleton


@app_state_singleton("pipeline_version_manager", PipelineVersionManager)
def get_pipeline_version_manager() -> PipelineVersionManager:
    """Возвращает PipelineVersionManager из app.state или lazy-init fallback."""
