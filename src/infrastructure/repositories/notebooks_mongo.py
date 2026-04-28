"""MongoDB-реализация ``NotebookRepository`` (Wave 9.1).

Коллекция ``notebooks`` — append-only история версий.
Документ соответствует ``Notebook`` model_dump (с ``_id == id``).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.infrastructure.clients.storage.mongodb import MongoDBClient, get_mongo_client
from src.services.notebooks.models import Notebook, NotebookVersion

__all__ = ("MongoNotebookRepository",)

logger = logging.getLogger(__name__)

_COLLECTION = "notebooks"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_notebook(doc: dict[str, Any]) -> Notebook:
    """Маппинг Mongo-документа в pydantic-модель."""
    payload = dict(doc)
    payload["id"] = payload.pop("_id", payload.get("id", ""))
    return Notebook.model_validate(payload)


def _notebook_to_doc(notebook: Notebook) -> dict[str, Any]:
    """Маппинг pydantic-модели в Mongo-документ."""
    payload = notebook.model_dump(mode="json")
    payload["_id"] = payload.pop("id")
    return payload


class MongoNotebookRepository:
    """MongoDB-имплементация Protocol ``NotebookRepository``."""

    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        """Создаёт индексы (idempotent). Вызывать после старта Mongo-клиента."""
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index("tags", name="tags_idx")
            await collection.create_index([("updated_at", -1)], name="updated_at_desc")
            await collection.create_index(
                [("is_deleted", 1), ("updated_at", -1)], name="is_deleted_updated_at"
            )
            await collection.create_index("title", name="title_idx")
        except Exception as exc:  # noqa: BLE001
            logger.warning("MongoNotebookRepository: ensure_indexes failed: %s", exc)

    async def create(self, notebook: Notebook) -> Notebook:
        await self._client().insert_one(_COLLECTION, _notebook_to_doc(notebook))
        return notebook

    async def get(self, notebook_id: str) -> Notebook | None:
        doc = await self._client().find_one(_COLLECTION, {"_id": notebook_id})
        return _doc_to_notebook(doc) if doc else None

    async def append_version(
        self,
        notebook_id: str,
        content: str,
        changed_by: str,
        summary: str | None = None,
    ) -> Notebook | None:
        client = self._client()
        existing = await client.find_one(
            _COLLECTION, {"_id": notebook_id, "is_deleted": {"$ne": True}}
        )
        if existing is None:
            return None
        new_version = int(existing.get("latest_version", 0)) + 1
        version_payload = NotebookVersion(
            version=new_version, content=content, changed_by=changed_by, summary=summary
        ).model_dump(mode="json")
        await client.collection(_COLLECTION).update_one(
            {"_id": notebook_id},
            {
                "$push": {"versions": version_payload},
                "$set": {
                    "latest_version": new_version,
                    "updated_at": _utc_now().isoformat(),
                },
            },
        )
        return await self.get(notebook_id)

    async def restore_version(
        self, notebook_id: str, version: int, changed_by: str
    ) -> Notebook | None:
        existing = await self.get(notebook_id)
        if existing is None or existing.is_deleted:
            return None
        target = next((v for v in existing.versions if v.version == version), None)
        if target is None:
            return None
        return await self.append_version(
            notebook_id, target.content, changed_by, summary=f"restore from v{version}"
        )

    async def list_all(
        self,
        *,
        tag: str | None = None,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Notebook]:
        query: dict[str, Any] = {}
        if not include_deleted:
            query["is_deleted"] = {"$ne": True}
        if tag is not None:
            query["tags"] = tag
        docs = await self._client().find(
            _COLLECTION,
            query=query,
            limit=limit,
            skip=offset,
            sort=[("updated_at", -1)],
        )
        return [_doc_to_notebook(d) for d in docs]

    async def soft_delete(self, notebook_id: str) -> bool:
        modified = await self._client().update_one(
            _COLLECTION,
            query={"_id": notebook_id},
            update={"is_deleted": True, "updated_at": _utc_now().isoformat()},
        )
        return modified > 0
