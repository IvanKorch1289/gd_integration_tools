"""MongoDB-имплементация ``ExpressDialogStore`` (Wave 9.2.4).

Коллекция ``express_dialogs``. Документ — `ExpressDialog`, ``_id == session_id``.
TTL-индекс по полю ``ttl`` (`expireAfterSeconds=0` — удаление при достижении).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.backend.core.di import app_state_singleton
from src.backend.core.models.express import ExpressDialog, ExpressMessage
from src.backend.infrastructure.clients.storage.mongodb import (
    MongoDBClient,
    get_mongo_client,
)

__all__ = ("MongoExpressDialogStore", "get_express_dialog_store")

logger = logging.getLogger(__name__)

_COLLECTION = "express_dialogs"
_DEFAULT_TTL = timedelta(days=30)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _doc_to_dialog(doc: dict[str, Any]) -> ExpressDialog:
    payload = dict(doc)
    payload.pop("_id", None)
    return ExpressDialog.model_validate(payload)


class MongoExpressDialogStore:
    """Mongo-реализация ``ExpressDialogStore``."""

    def __init__(self, client_factory: Any | None = None) -> None:
        self._client_factory = client_factory or get_mongo_client

    def _client(self) -> MongoDBClient:
        return self._client_factory()

    async def ensure_indexes(self) -> None:
        try:
            collection = self._client().collection(_COLLECTION)
            await collection.create_index(
                [("group_chat_id", 1), ("updated_at", -1)], name="chat_updated"
            )
            await collection.create_index(
                "ttl", name="ttl_expire", expireAfterSeconds=0
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("MongoExpressDialogStore: ensure_indexes failed: %s", exc)

    async def append_message(
        self,
        session_id: str,
        role: str,
        body: str,
        *,
        bot_id: str | None = None,
        group_chat_id: str | None = None,
        user_huid: str | None = None,
        sync_id: str | None = None,
        bubble: dict[str, Any] | None = None,
        keyboard: dict[str, Any] | None = None,
    ) -> None:
        message = ExpressMessage(
            role=role, body=body, sync_id=sync_id, bubble=bubble, keyboard=keyboard
        ).model_dump(mode="json")
        now = _utc_now()
        ttl = (now + _DEFAULT_TTL).isoformat()

        set_on_insert: dict[str, Any] = {
            "_id": session_id,
            "session_id": session_id,
            "created_at": now.isoformat(),
            "ttl": ttl,
        }
        if bot_id is not None:
            set_on_insert["bot_id"] = bot_id
        if group_chat_id is not None:
            set_on_insert["group_chat_id"] = group_chat_id
        if user_huid is not None:
            set_on_insert["user_huid"] = user_huid

        try:
            await (
                self._client()
                .collection(_COLLECTION)
                .update_one(
                    {"_id": session_id},
                    {
                        "$push": {"messages": message},
                        "$set": {"updated_at": now.isoformat()},
                        "$setOnInsert": set_on_insert,
                    },
                    upsert=True,
                )
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "ExpressDialogStore.append_message failed (%s): %s", session_id, exc
            )

    async def get_by_session(self, session_id: str) -> ExpressDialog | None:
        doc = await self._client().find_one(_COLLECTION, {"_id": session_id})
        return _doc_to_dialog(doc) if doc else None

    async def list_by_chat(
        self, group_chat_id: str, limit: int = 100
    ) -> list[ExpressDialog]:
        docs = await self._client().find(
            _COLLECTION,
            query={"group_chat_id": group_chat_id},
            limit=limit,
            sort=[("updated_at", -1)],
        )
        return [_doc_to_dialog(d) for d in docs]

    async def update_context(
        self, session_id: str, context_delta: dict[str, Any]
    ) -> None:
        if not context_delta:
            return
        update = {f"context.{k}": v for k, v in context_delta.items()}
        update["updated_at"] = _utc_now().isoformat()
        await self._client().update_one(
            _COLLECTION, query={"_id": session_id}, update=update, upsert=True
        )


@app_state_singleton("express_dialog_store", factory=MongoExpressDialogStore)
def get_express_dialog_store() -> MongoExpressDialogStore:
    """Singleton ``MongoExpressDialogStore``."""
