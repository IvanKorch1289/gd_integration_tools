"""ABC ``AuditBackend`` — append-only лог аудит-событий.

Wave 21.3c. Реализации:

* :class:`infrastructure.audit.jsonl_audit.JsonlAuditBackend` — append-only
  JSONL файл (для dev_light / тестов / single-host deployments);
* (используется) :class:`infrastructure.audit.event_log.AuditEventLog` —
  ClickHouse-backed batch flusher (production).

Контракт минимален: append + query. Без удаления (audit append-only
по определению).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

__all__ = ("AuditBackend", "AuditRecord")


class AuditRecord(dict[str, Any]):
    """Lightweight typed-dict для аудит-записи. Используется как
    ``AuditRecord({"event": "user.login", "actor": "user-1", ...})``.

    Не вводим Pydantic-модель, чтобы не тащить лишнюю валидацию в hot-path.
    """


class AuditBackend(ABC):
    """Append-only лог аудит-событий.

    Реализация ДОЛЖНА быть thread-safe / async-safe (последовательные
    ``append`` могут идти из нескольких корутин).
    """

    @abstractmethod
    async def append(self, record: AuditRecord) -> None:
        """Добавляет запись в журнал."""
        ...

    @abstractmethod
    async def query(
        self,
        *,
        limit: int = 100,
        filters: dict[str, Any] | None = None,
    ) -> list[AuditRecord]:
        """Возвращает последние ``limit`` записей, опционально по фильтру.

        ``filters`` — простой equality-match по полям; реализация может
        поддерживать любое подмножество (например JSONL — линейно перебирает,
        ClickHouse — формирует SQL).
        """
        ...
