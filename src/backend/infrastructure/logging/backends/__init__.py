"""Реализации :class:`~src.core.interfaces.log_sink.LogSink`.

Wave 2.5 (Roadmap V10):

* :class:`ConsoleJsonLogSink` — stdout JSON через ``orjson`` (dev_light).
* :class:`DiskRotatingLogSink` — ротируемый файл через
  ``logging.handlers.RotatingFileHandler`` в потоке.
* :class:`GraylogGelfLogSink` — GELF в Graylog (UDP/TCP) с circuit-breaker
  через ``purgatory``; при downtime автоматический fallback на disk
  организуется на уровне router.
"""

from __future__ import annotations

from src.backend.infrastructure.logging.backends.console_json import ConsoleJsonLogSink
from src.backend.infrastructure.logging.backends.disk_rotating import (
    DiskRotatingLogSink,
)
from src.backend.infrastructure.logging.backends.graylog_gelf import GraylogGelfLogSink

__all__ = ("ConsoleJsonLogSink", "DiskRotatingLogSink", "GraylogGelfLogSink")
