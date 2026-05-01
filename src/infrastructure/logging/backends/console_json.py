"""``ConsoleJsonLogSink`` — JSON в stdout через ``orjson``.

Используется в профиле ``dev_light``: лёгкий, без сетевых зависимостей,
всегда healthy. Сериализация — через ``orjson`` (стандартный JSON-движок
проекта, заметно быстрее stdlib ``json``).
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any, Final, TextIO

import orjson

from src.core.interfaces.log_sink import LogSink

__all__ = ("ConsoleJsonLogSink",)

_ORJSON_OPTS: Final[int] = orjson.OPT_APPEND_NEWLINE | orjson.OPT_NAIVE_UTC


class ConsoleJsonLogSink(LogSink):
    """JSON-логи в stdout (или произвольный текстовый поток).

    Аргументы:
        stream: выходной поток. По умолчанию :data:`sys.stdout`.
        name: имя sink-а для метрик. По умолчанию ``"console_json"``.

    Поведение:
        * сериализация через ``orjson.dumps`` с ``OPT_APPEND_NEWLINE``;
        * запись — через :func:`asyncio.to_thread`, чтобы не блокировать
          event loop при медленных терминалах / редиректах в pipe;
        * при ошибке сериализации/записи sink остаётся healthy
          (поток stdout считается всегда доступным), но запись
          теряется и помечается через ``is_healthy = False`` лишь
          если сам поток упал (rare).
    """

    def __init__(
        self, *, stream: TextIO | None = None, name: str = "console_json"
    ) -> None:
        self.name = name
        self.is_healthy = True
        self._stream: TextIO = stream if stream is not None else sys.stdout

    async def write(self, record: dict[str, Any]) -> None:
        """Сериализовать ``record`` и записать в поток одной строкой."""
        try:
            payload = orjson.dumps(
                record, default=_default_serializer, option=_ORJSON_OPTS
            )
        except (TypeError, ValueError):
            # повторная попытка с агрессивным fallback: всё неподдержанное → str
            payload = orjson.dumps(
                {k: _coerce(v) for k, v in record.items()}, option=_ORJSON_OPTS
            )
        await asyncio.to_thread(self._write_bytes, payload)

    async def flush(self) -> None:
        """Сбросить буфер выходного потока."""
        await asyncio.to_thread(self._stream.flush)

    async def close(self) -> None:
        """Закрытие не требуется: ``sys.stdout`` принадлежит интерпретатору."""
        try:
            await self.flush()
        except OSError:
            self.is_healthy = False

    def _write_bytes(self, payload: bytes) -> None:
        """Безопасная запись байтов в текстовый поток."""
        try:
            self._stream.write(payload.decode("utf-8"))
        except OSError:
            self.is_healthy = False


def _default_serializer(value: Any) -> Any:
    """Fallback для ``orjson.dumps`` — приводит неподдержанные типы к ``str``."""
    return str(value)


def _coerce(value: Any) -> Any:
    """Жёсткое приведение значения к JSON-совместимому типу."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)
