"""``DiskRotatingLogSink`` — JSON в ротируемый файл.

Использует stdlib :class:`logging.handlers.RotatingFileHandler`
обёрнутый в :func:`asyncio.to_thread` для async-friendly API.
Подходит как fallback при недоступности Graylog и как локальный
архив для dev/staging/prod профилей.
"""

from __future__ import annotations

import asyncio
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Final

import orjson

from src.backend.core.interfaces.log_sink import LogSink

__all__ = ("DiskRotatingLogSink",)

_DEFAULT_MAX_BYTES: Final[int] = 50 * 1024 * 1024  # 50 MiB
_DEFAULT_BACKUP_COUNT: Final[int] = 7
_ORJSON_OPTS: Final[int] = orjson.OPT_NAIVE_UTC


class DiskRotatingLogSink(LogSink):
    """Файловый sink с ротацией по размеру.

    Аргументы:
        path: путь к лог-файлу; родительский каталог создаётся автоматически.
        max_bytes: максимальный размер одного файла перед ротацией.
        backup_count: сколько ротированных файлов хранить.
        name: имя sink-а для метрик. По умолчанию ``"disk_rotating"``.
        encoding: кодировка файла. По умолчанию ``"utf-8"``.

    Поведение:
        * каждая запись сериализуется как одна JSON-строка через ``orjson``;
        * сама запись делегируется в :class:`RotatingFileHandler` через
          :func:`asyncio.to_thread`, чтобы не блокировать event loop;
        * при ошибке I/O sink помечается ``is_healthy = False`` —
          router может переключиться на другой backend.
    """

    def __init__(
        self,
        *,
        path: str | Path,
        max_bytes: int = _DEFAULT_MAX_BYTES,
        backup_count: int = _DEFAULT_BACKUP_COUNT,
        name: str = "disk_rotating",
        encoding: str = "utf-8",
    ) -> None:
        self.name = name
        self.is_healthy = True
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._handler: RotatingFileHandler = RotatingFileHandler(
            filename=str(self._path),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding=encoding,
            delay=True,
        )
        # форматирование делаем сами — handler работает как «голый» writer
        self._handler.setFormatter(logging.Formatter("%(message)s"))

    async def write(self, record: dict[str, Any]) -> None:
        """Записать ``record`` в файл; ошибки I/O ловятся внутри."""
        try:
            payload = orjson.dumps(
                record, default=_default_serializer, option=_ORJSON_OPTS
            ).decode("utf-8")
        except TypeError, ValueError:
            payload = orjson.dumps(
                {k: _coerce(v) for k, v in record.items()}, option=_ORJSON_OPTS
            ).decode("utf-8")

        await asyncio.to_thread(self._emit, payload)

    async def flush(self) -> None:
        """Сбросить файловый буфер."""
        await asyncio.to_thread(self._safe_flush)

    async def close(self) -> None:
        """Закрыть handler и освободить файловый дескриптор."""
        await asyncio.to_thread(self._handler.close)

    # ------------------------------------------------------------------ helpers
    def _emit(self, payload: str) -> None:
        """Синхронная запись через stdlib handler."""
        record = logging.LogRecord(
            name=self.name,
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg=payload,
            args=None,
            exc_info=None,
        )
        try:
            self._handler.emit(record)
        except OSError:
            self.is_healthy = False

    def _safe_flush(self) -> None:
        """Сбросить буфер с подавлением I/O ошибок."""
        try:
            self._handler.flush()
        except OSError:
            self.is_healthy = False


def _default_serializer(value: Any) -> Any:
    """Fallback сериализатор: всё неизвестное → ``str``."""
    return str(value)


def _coerce(value: Any) -> Any:
    """Жёсткое приведение к JSON-типам."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)
