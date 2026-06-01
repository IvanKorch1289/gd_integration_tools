"""LogIndexer — дублирование audit-логов в Elasticsearch (Wave 9.3.1).

ClickHouse остаётся primary store (долгосрочное хранилище и аналитика);
Elasticsearch — secondary search index (полнотекстовый поиск, фильтры по
``entity_type``/``tenant_id``). ES-сбой не должен ломать ClickHouse-flush —
вызывается через try/except в ``AuditEventLog._flush_to_clickhouse``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.backend.core.di import app_state_singleton

if TYPE_CHECKING:
    from src.backend.services.io.search import SearchService

__all__ = ("LogIndexer", "get_log_indexer")

logger = logging.getLogger(__name__)

_AUDIT_INDEX = "audit_logs"

_AUDIT_MAPPINGS: dict[str, Any] = {
    "properties": {
        "who": {"type": "text", "fields": {"keyword": {"type": "keyword"}}},
        "what": {"type": "text"},
        "entity_type": {"type": "keyword"},
        "entity_id": {"type": "keyword"},
        "action": {"type": "keyword"},
        "when": {"type": "date"},
        "before_data": {"type": "object", "enabled": True},
        "after_data": {"type": "object", "enabled": True},
        "correlation_id": {"type": "keyword"},
        "tenant_id": {"type": "keyword"},
        "metadata": {"type": "object", "enabled": True},
    }
}


class LogIndexer:
    """Bulk-индексирует ``AuditEvent``ы в ES индекс ``gd_audit_logs``."""

    def __init__(
        self, search_service: SearchService, *, index: str = _AUDIT_INDEX
    ) -> None:
        self._search = search_service
        self._index = index

    async def ensure_index(self) -> None:
        """Создаёт индекс с маппингом (idempotent)."""
        try:
            await self._search.ensure_index(self._index, mappings=_AUDIT_MAPPINGS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LogIndexer.ensure_index failed: %s", exc)

    async def index_batch(self, events: list[Any]) -> None:
        """Индексирует пачку событий. Молча логирует ошибки."""
        if not events:
            return
        try:
            docs = [self._event_to_doc(e) for e in events]
            await self._search.bulk_index(self._index, docs)
        except Exception as exc:  # noqa: BLE001
            logger.warning("LogIndexer.index_batch failed: %s", exc)

    @staticmethod
    def _event_to_doc(event: Any) -> dict[str, Any]:
        """Маппит ``AuditEvent`` в ES-документ."""
        return {
            "who": getattr(event, "who", ""),
            "what": getattr(event, "what", ""),
            "entity_type": getattr(event, "entity_type", ""),
            "entity_id": getattr(event, "entity_id", ""),
            "action": getattr(event, "action", ""),
            "when": getattr(event, "when").isoformat()
            if getattr(event, "when", None) is not None
            else None,
            "before_data": getattr(event, "before", None) or {},
            "after_data": getattr(event, "after", None) or {},
            "correlation_id": getattr(event, "correlation_id", ""),
            "tenant_id": getattr(event, "tenant_id", ""),
            "metadata": getattr(event, "metadata", {}) or {},
        }


def _factory() -> LogIndexer:
    from src.backend.services.io.search import get_search_service

    return LogIndexer(get_search_service())


@app_state_singleton("log_indexer", factory=_factory)
def get_log_indexer() -> LogIndexer:
    """Singleton ``LogIndexer``."""
