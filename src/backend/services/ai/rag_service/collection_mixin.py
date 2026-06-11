from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    pass


class CollectionMixin:
    """collection ops (delete/delete_collection/stats/count) для RAGService. S64 W4 extraction."""

    __slots__ = ()

    async def delete(self, document_id: str) -> bool:
        """Удаляет документ из индекса (по chunk-id'ам или doc_id)."""
        try:
            await self._store.delete([document_id])
            await self._invalidate_namespace(None)
            return True
        except Exception as _:
            return False

    async def delete_collection(self, namespace: str) -> int:
        """Удаляет все документы из логической партиции (namespace).

        Использует ``BaseVectorStore.delete_where({"namespace": namespace})``.
        Возвращает количество удалённых chunks. При ошибке — 0.
        """
        try:
            removed = int(await self._store.delete_where({"namespace": namespace}))
            await self._invalidate_namespace(namespace)
            return removed
        except NotImplementedError:
            logger.warning(
                "delete_where не поддерживается backend'ом — namespace %s не очищен",
                namespace,
            )
            return 0
        except Exception as exc:
            logger.warning("delete_collection(%s) failed: %s", namespace, exc)
            return 0

    async def get_collection_stats(self, namespace: str) -> dict[str, Any]:
        """Статистика по namespace: количество chunks + базовые метаданные.

        Возвращает: ``{"namespace": str, "count": int, "exists": bool}``.
        Backend'ы без ``count_where`` отдают ``count=0``.
        """
        try:
            cnt = int(await self._store.count_where({"namespace": namespace}))
        except NotImplementedError:
            cnt = 0
        except Exception as exc:
            logger.warning("get_collection_stats(%s) failed: %s", namespace, exc)
            cnt = 0
        return {"namespace": namespace, "count": cnt, "exists": cnt > 0}

    async def count(self, collection: str | None = None) -> int:
        """Количество документов: всего или в конкретной namespace.

        ``collection`` — если задан, фильтрует по metadata ``namespace``.
        Возвращает 0 при недоступности backend.
        """
        try:
            if collection is None:
                return int(await self._store.count())
            return int(await self._store.count_where({"namespace": collection}))
        except NotImplementedError:
            return 0
        except Exception as exc:
            logger.warning("count(%s) failed: %s", collection, exc)
            return 0
