"""OrderIndexer — индексация заказов в Elasticsearch (Wave 9.3.2).

Postgres остаётся source-of-truth; ES — secondary search index для
полнотекстового поиска и фасетных фильтров (статус, дата). Hooks
выставляются в ``OrderService`` (best-effort fire-and-forget).
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from src.core.di import app_state_singleton

if TYPE_CHECKING:
    from src.services.io.search import SearchService

__all__ = ("OrderIndexer", "get_order_indexer")

logger = logging.getLogger(__name__)

_ORDERS_INDEX = "orders"

_ORDERS_MAPPINGS: dict[str, Any] = {
    "properties": {
        "id": {"type": "keyword"},
        "pledge_gd_id": {"type": "keyword"},
        "order_kind_id": {"type": "keyword"},
        "status": {"type": "keyword"},
        "created_at": {"type": "date"},
        "updated_at": {"type": "date"},
        "metadata": {"type": "object", "enabled": True},
    }
}


class OrderIndexer:
    """Индексирует Order-записи в ES."""

    def __init__(
        self, search_service: SearchService, *, index: str = _ORDERS_INDEX
    ) -> None:
        self._search = search_service
        self._index = index

    async def ensure_index(self) -> None:
        try:
            await self._search.ensure_index(self._index, mappings=_ORDERS_MAPPINGS)
        except Exception as exc:  # noqa: BLE001
            logger.warning("OrderIndexer.ensure_index failed: %s", exc)

    async def index_one(self, order: Any) -> None:
        """Индексирует один Order. ID документа — ``order.id`` (str)."""
        try:
            doc = self._order_to_doc(order)
            await self._search.index_document(self._index, doc, doc_id=str(doc["id"]))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OrderIndexer.index_one failed: %s", exc)

    async def delete_one(self, order_id: Any) -> None:
        try:
            await self._search.delete_document(self._index, str(order_id))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OrderIndexer.delete_one failed: %s", exc)

    async def bulk_reindex(self, orders: list[Any]) -> int:
        """Полная переиндексация переданного списка заказов."""
        if not orders:
            return 0
        try:
            docs = [self._order_to_doc(o) for o in orders]
            result = await self._search.bulk_index(self._index, docs, id_field="id")
            return int(result.get("indexed", 0))
        except Exception as exc:  # noqa: BLE001
            logger.warning("OrderIndexer.bulk_reindex failed: %s", exc)
            return 0

    def index_one_fire_and_forget(self, order: Any) -> None:
        """Не блокирует caller — отправляет index_one через ``create_task``."""
        try:
            asyncio.create_task(self.index_one(order))
        except RuntimeError:
            # Нет event loop'а — пропускаем.
            return

    @staticmethod
    def _order_to_doc(order: Any) -> dict[str, Any]:
        """Маппинг Order-объекта (ORM или DTO) в ES-документ."""

        def _g(name: str, default: Any = None) -> Any:
            return getattr(order, name, default)

        created = _g("created_at")
        updated = _g("updated_at")
        return {
            "id": str(_g("id", "")),
            "pledge_gd_id": str(_g("pledge_gd_id", "") or ""),
            "order_kind_id": str(_g("order_kind_id", "") or ""),
            "status": str(_g("status", "") or ""),
            "created_at": created.isoformat() if created else None,
            "updated_at": updated.isoformat() if updated else None,
            "metadata": dict(_g("metadata", {}) or {}),
        }


def _factory() -> OrderIndexer:
    from src.services.io.search import get_search_service

    return OrderIndexer(get_search_service())


@app_state_singleton("order_indexer", factory=_factory)
def get_order_indexer() -> OrderIndexer:
    """Singleton ``OrderIndexer``."""
