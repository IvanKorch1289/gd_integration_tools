"""DLQ writers — per-transport реализации (Sprint 9 K2 W1).

Composition root выбирает writer по конфигурации.
Все реализации совместимы с :class:`DLQWriter` Protocol.

Public-API: импорт ``DLQEnvelope``/``DLQReason``/``DLQWriter`` сохранён
через re-export из :mod:`infrastructure.messaging.dlq_base` —
backwards-compat для S8 importers.

Доступные writers:

* :class:`InMemoryDLQWriter` — для unit-тестов и dev_light.
* :class:`KafkaDLQWriter` — Kafka topic dlq.{transport}.
* :class:`RabbitDLQWriter` — RabbitMQ queue dlq.{transport}.
* :class:`NATSDLQWriter` — NATS subject dlq.{transport}.
* :class:`InboxDLQWriter` — Postgres dlq_inbox table.
* :class:`FanoutDLQWriter` — публикует в несколько writers (для replay).

Lazy loading (cycle 158+ Option A из STARTUP_BOTTLENECK_INVESTIGATION):
original design eagerly импортировал 6 writer-классов + dlq_base.
Полное время cold-import = ~9.5s (per DLQ_REGRESSION_2026-09-24
investigation). Удалён eager pattern в пользу lazy ``__getattr__`` proxy:
producer (composition root, tests) делает реальный import только когда
name requested.
"""

from __future__ import annotations

import importlib as _importlib
from typing import Any as _Any

_LAZY_MAP: dict[str, str] = {
    # dlq_base is SIBLING module (не submodule of dlq/):
    # src/backend/infrastructure/messaging/dlq_base.py.
    # Direct absolute path required.
    "DLQEnvelope": "src.backend.infrastructure.messaging.dlq_base",
    "DLQReason": "src.backend.infrastructure.messaging.dlq_base",
    "DLQWriter": "src.backend.infrastructure.messaging.dlq_base",
    # Per-writer submodules (relative path: .<submodule>).
    "FanoutDLQWriter": "fanout_writer",
    "InboxDLQWriter": "inbox_writer",
    "KafkaDLQWriter": "kafka_writer",
    "InMemoryDLQWriter": "memory_writer",
    "NATSDLQWriter": "nats_writer",
    "RabbitDLQWriter": "rabbit_writer",
}
"""Mapping ``name -> target module path`` для lazy proxy.

Sibling modules (dlq_base) используют absolute path ``src.backend...``.
Submodules (writer files) используют relative path — ``__getattr__``
добавляет ``.`` prefix.
"""


def __getattr__(name: str) -> _Any:  # PEP 562 lazy module attribute.
    """Lazy import — load target module когда name впервые requested.

    Saves ~9.5s в startup_time.py cold-import (per
    DLQ_REGRESSION_2026-09-24).

    Cache результат в ``_cached`` per process для repeated lookups
    (avoid re-import overhead).
    """
    if name in _LAZY_MAP:
        target = _LAZY_MAP[name]
        # Submodules: prefix с ``.`` для relative import.
        # Sibling modules: use as-is (absolute path).
        if target.startswith("src."):
            module_spec = target
        else:
            module_spec = f".{target}"
        module = _importlib.import_module(module_spec, __name__)
        value = getattr(module, name)
        _cached[name] = value
        return value
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_cached: dict[str, _Any] = {}
"""Cache resolved attributes для subsequent ``__getattr__`` lookups
в пределах одного процесса. Cleared only на interpreter restart."""


def __dir__() -> list[str]:
    """``dir()`` через lazy proxy + cached для tab-completion support."""
    return sorted(set(__all__) | set(_cached.keys()))


__all__ = (
    "DLQEnvelope",
    "DLQReason",
    "DLQWriter",
    "FanoutDLQWriter",
    "InMemoryDLQWriter",
    "InboxDLQWriter",
    "KafkaDLQWriter",
    "NATSDLQWriter",
    "RabbitDLQWriter",
)
