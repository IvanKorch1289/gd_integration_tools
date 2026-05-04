"""``JsonlAuditBackend`` — append-only JSONL fallback (Wave 21.3c).

Используется в dev_light, где ClickHouse недоступен. Каждая запись —
отдельная строка JSON. Чтение для ``query`` идёт хвостом файла (читается
последние ``limit`` строк через streaming-обратный обход).
"""

from __future__ import annotations

import asyncio
import os
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import orjson

from src.core.interfaces.audit import AuditBackend, AuditRecord
from src.utilities.json_codec import dumps_str

__all__ = ("JsonlAuditBackend",)


class JsonlAuditBackend(AuditBackend):
    """Append-only JSONL backend.

    ``path`` — целевой файл (директория создаётся при необходимости).
    Каждый ``append`` атомарно дописывает строку и сбрасывает буфер на
    диск (``fsync`` опционален — best-effort).
    """

    def __init__(self, path: str | Path, *, fsync: bool = False) -> None:
        self._path = Path(path)
        self._fsync = fsync
        self._lock = asyncio.Lock()
        self._path.parent.mkdir(parents=True, exist_ok=True)

    async def append(self, record: AuditRecord) -> None:
        line = self._serialize(record)
        async with self._lock:
            await asyncio.to_thread(self._write_line, line)

    async def query(
        self, *, limit: int = 100, filters: dict[str, Any] | None = None
    ) -> list[AuditRecord]:
        if not self._path.exists():
            return []
        return await asyncio.to_thread(self._tail, limit, filters)

    def _write_line(self, line: str) -> None:
        with self._path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
            if self._fsync:
                f.flush()
                os.fsync(f.fileno())

    def _tail(self, limit: int, filters: dict[str, Any] | None) -> list[AuditRecord]:
        # Линейное чтение и буфер из последних N — для JSONL это нормально
        # на dev-объёмах (10^4–10^5 записей). Для production остаётся
        # ClickHouse-реализация.
        buf: deque[AuditRecord] = deque(maxlen=limit)
        with self._path.open("r", encoding="utf-8") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = AuditRecord(orjson.loads(raw))
                except orjson.JSONDecodeError:
                    continue
                if filters is None or all(rec.get(k) == v for k, v in filters.items()):
                    buf.append(rec)
        return list(buf)

    @staticmethod
    def _serialize(record: AuditRecord) -> str:
        # ``timestamp`` дополняется автоматически, если caller не задал.
        if "timestamp" not in record:
            record["timestamp"] = datetime.now(UTC).isoformat()
        return dumps_str(record)
