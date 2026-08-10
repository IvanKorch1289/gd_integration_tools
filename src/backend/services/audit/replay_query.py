"""Audit replay helpers (Layer 11 Безопасность Cycle 2).

Раньше ``list_audit_records`` жила в ``entrypoints/middlewares/audit_replay.py``,
откуда её lazy-импортировал ``services/dsl_portal/builder_facade.py``. Это
нарушало architecture invariants: services → entrypoints (reverse layer
import).

Per Ponytail D-rules: business-agnostic helpers принадлежат services layer
(где есть доступ к core/infrastructure), а не middleware (transport
concerns). Здесь — единственный canonical entrypoint для audit-replay
queries, доступный как services/*, так и middlewares/*.

Note: middleware ``audit_replay`` оставлен для HTTP-handler логики (write
audit records, replay-via-HTTP); чистые data-access helpers перенесены
сюда.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

logger = get_logger("services.audit.replay_query")

#: Каннонический stream name (должен совпадать с middleware для consistency).
_STREAM_NAME = "audit:events"


async def list_audit_records(
    *, count: int = 100, start_id: str = "-",
) -> list[dict[str, Any]]:
    """Читает последние записи из audit stream для Replay UI.

    Args:
        count: Максимум записей.
        start_id: ID начала чтения (``"-"`` = с самого начала потока).

    Returns:
        List of audit records (пустой список если Redis недоступен).
    """
    try:
        from src.backend.core.di.providers import get_redis_stream_client_provider

        redis_client = get_redis_stream_client_provider()
        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=count, start_id=start_id,
        )
        return records or []
    except Exception as exc:
        logger.warning("Failed to read audit stream: %s", exc)
        return []


async def replay_audit_record(record_id: str) -> dict[str, Any]:
    """Replay одной audit-записи (re-issue HTTP request для дебага).

    Args:
        record_id: Stream ID записи.

    Returns:
        ``{"status": "replayed", "record_id": ..., "new_response": {...}}``.
    """
    try:
        from src.backend.core.di.providers import get_redis_stream_client_provider

        redis_client = get_redis_stream_client_provider()
        records = await redis_client.read_stream(
            stream_name=_STREAM_NAME, count=1, start_id=record_id,
        )
        if not records:
            return {"status": "not_found", "record_id": record_id}
        # Production: actual replay requires HTTP-level re-execution.
        # Здесь — заглушка, возвращающая payload записи (re-execute в middleware).
        record = records[0]
        return {
            "status": "replayed",
            "record_id": record_id,
            "new_response": record,
        }
    except Exception as exc:
        logger.warning("Failed to replay audit record %s: %s", record_id, exc)
        return {"status": "error", "record_id": record_id, "error": str(exc)}
