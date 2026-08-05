"""B-17 fix (cycle 37): DLQ-writer wiring guard для CDCClient singleton.

``CDCClient`` (singleton, ``get_cdc_client()``) принимает ``DLQWriter`` через
:meth:`set_dlq_writer`, но до cycle 37 в production-стенде этот setter
никем не вызывался — ``_send_to_dlq`` делал ``return`` при ``writer is None``
и событие тихо терялось.

Этот guard-объект решает проблему observability: факт wiring'а
регистрируется в :data:`_wired` и проверяется через :meth:`is_wired`.
Composition root (``plugins/composition/di.py``) ОБЯЗАН вызвать
:func:`mark_cdc_dlq_writer_wired` сразу после ``cdc.set_dlq_writer(...)``;
иначе CDCClient._send_to_dlq в production поднимет ``RuntimeError``
(fail-loud, см. ``CDCClient._send_to_dlq``).
"""

from __future__ import annotations

import threading
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.infrastructure.messaging.dlq_base import DLQWriter

__all__ = (
    "DLQWriterGuard",
    "cdc_dlq_writer_guard",
    "mark_cdc_dlq_writer_wired",
)

logger = get_logger(__name__)


class DLQWriterGuard:
    """Thread-safe флаг: ``set_dlq_writer()`` был вызван хоть раз.

    Использование:

    1. ``InboxDLQWriter`` создаётся в composition root.
    2. ``cdc.set_dlq_writer(writer)`` устанавливает writer в singleton.
    3. :func:`mark_cdc_dlq_writer_wired` фиксирует факт wiring'а.

    Проверка:

    * :meth:`is_wired` — production smoke-test (``startup logging``).
    * В ``_send_to_dlq`` — fail-loud (``RuntimeError``) если required.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wired: bool = False
        self._writer_ref: "DLQWriter | None" = None
        self._wired_at_count: int = 0

    def mark_wired(self, writer: "DLQWriter | None" = None) -> None:
        """Зафиксировать факт wiring'а writer'а в CDC singleton.

        Args:
            writer: Опциональная weak-ссылка на writer (для logging / debug).
        """
        with self._lock:
            self._wired = True
            self._writer_ref = writer
            self._wired_at_count += 1
        logger.info(
            "CDC DLQ writer marked as wired (count=%d, writer=%s)",
            self._wired_at_count,
            type(writer).__name__ if writer is not None else "None",
        )

    def reset(self) -> None:
        """Сбросить флаг (для tests)."""
        with self._lock:
            self._wired = False
            self._writer_ref = None
            self._wired_at_count = 0

    def is_wired(self) -> bool:
        """``True`` если :meth:`mark_wired` был вызван и не было :meth:`reset`."""
        with self._lock:
            return self._wired

    def writer_ref(self) -> "DLQWriter | None":
        """Optional reference to last wired writer (read-only)."""
        with self._lock:
            return self._writer_ref


# Module-level singleton guard.
cdc_dlq_writer_guard: DLQWriterGuard = DLQWriterGuard()


def mark_cdc_dlq_writer_wired(writer: "DLQWriter | None" = None) -> None:
    """Convenience wrapper для composition root.

    Вызывается из ``plugins/composition/di.py`` сразу после
    ``cdc.set_dlq_writer(writer)``.
    """
    cdc_dlq_writer_guard.mark_wired(writer)
