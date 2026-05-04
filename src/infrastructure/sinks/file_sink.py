"""FileSink — append/write на local FS (Wave 3.1).

Полезен для DSL-сценариев экспорта (audit-trail, archive,
debug-dump). Атомарность достигается через write-temp + rename
для режима ``"write"``; для ``"append"`` — обычный async-append
через ``aiofiles`` (если есть) или ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from src.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.utilities.json_codec import dumps_str

__all__ = ("FileSink",)


@dataclass(slots=True)
class FileSink(Sink):
    """Sink для записи payload в файл local FS.

    Args:
        sink_id: Уникальный идентификатор.
        path: Путь к файлу.
        mode: ``"append"`` (NDJSON по строке на payload) или
            ``"write"`` (атомарная замена через write-temp+rename).
        encoding: Кодировка текста (``"utf-8"`` по умолчанию).
        ensure_dir: Создавать ли parent dir если отсутствует.
    """

    sink_id: str
    path: str
    mode: Literal["append", "write"] = "append"
    encoding: str = "utf-8"
    ensure_dir: bool = True
    kind: SinkKind = field(default=SinkKind.FILE, init=False)

    async def send(self, payload: Any) -> SinkResult:
        """Сериализует ``payload`` (JSON если dict/list) и пишет в файл."""
        target = Path(self.path)
        if self.ensure_dir:
            target.parent.mkdir(parents=True, exist_ok=True)

        text = payload if isinstance(payload, str) else dumps_str(payload)

        try:
            written = await asyncio.to_thread(self._write_sync, target, text)
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False,
                details={"error": str(exc) or exc.__class__.__name__},
            )

        return SinkResult(
            ok=True,
            external_id=str(target),
            details={"bytes": written, "mode": self.mode},
        )

    def _write_sync(self, target: Path, text: str) -> int:
        """Синхронная запись (вызывается через ``asyncio.to_thread``)."""
        if self.mode == "append":
            line = text if text.endswith("\n") else text + "\n"
            with target.open("a", encoding=self.encoding) as fh:
                return fh.write(line)
        # mode == "write" → write-temp + rename.
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=str(target.parent),
            prefix=f".{target.name}.",
            suffix=".tmp",
            encoding=self.encoding,
            delete=False,
        ) as tmp:
            written = tmp.write(text)
            tmp_path = Path(tmp.name)
        os.replace(tmp_path, target)
        return written

    async def health(self) -> bool:
        """Доступна ли parent-директория для записи."""
        target = Path(self.path)
        parent = target.parent
        if self.ensure_dir:
            try:
                parent.mkdir(parents=True, exist_ok=True)
            except OSError:
                return False
        return parent.is_dir() and os.access(parent, os.W_OK)
