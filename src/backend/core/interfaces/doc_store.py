"""ABC ``DocStoreBackend`` — контракт document-store (Wave 21.3c).

Замена Mongo-репозиториев для dev_light. Реализации:

* :class:`infrastructure.storage.sqlite_doc_store.SqliteDocStore` — SQLite
  с JSON-колонкой (для dev_light / тестов);
* (используется) Mongo-репозитории в ``infrastructure/repositories/*_mongo.py``
  (production).

Контракт — namespaced kv-store с фильтрами по полям документа. Не
претендует на полный Mongo API: запросы — equality / range / списки.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("DocStoreBackend",)


class DocStoreBackend(ABC):
    """Контракт document-store (namespaced JSON-документы с фильтрами)."""

    @abstractmethod
    async def insert(
        self, namespace: str, doc: dict[str, Any], *, doc_id: str | None = None
    ) -> str:
        """Вставляет документ в namespace; возвращает ``doc_id``.

        Если ``doc_id`` не задан, реализация генерирует его сама.
        """
        ...

    @abstractmethod
    async def get(self, namespace: str, doc_id: str) -> dict[str, Any] | None:
        """Возвращает документ по идентификатору или ``None``."""
        ...

    @abstractmethod
    async def update(self, namespace: str, doc_id: str, patch: dict[str, Any]) -> bool:
        """Применяет patch к документу (merge).

        Возвращает ``True``, если документ существовал.
        """
        ...

    @abstractmethod
    async def delete(self, namespace: str, doc_id: str) -> bool:
        """Удаляет документ; возвращает ``True``, если существовал."""
        ...

    @abstractmethod
    async def find(
        self,
        namespace: str,
        *,
        filters: dict[str, Any] | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Возвращает документы из namespace, опционально по equality-фильтру."""
        ...

    @abstractmethod
    async def count(self, namespace: str, filters: dict[str, Any] | None = None) -> int:
        """Возвращает количество документов в namespace по фильтру."""
        ...
