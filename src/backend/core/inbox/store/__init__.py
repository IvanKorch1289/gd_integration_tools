"""Storage backends for InboxService."""

from src.backend.core.inbox.store.base import InboxEntry, InboxStore
from src.backend.core.inbox.store.in_memory import InMemoryInboxStore

__all__ = ("InboxEntry", "InboxStore", "InMemoryInboxStore")
