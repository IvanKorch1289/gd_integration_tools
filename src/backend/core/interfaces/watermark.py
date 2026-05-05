"""W14.3 — Protocol для источников событий, эмитящих watermarks.

Source, реализующий :class:`WatermarkEmitter`, объявляет монотонную
границу "не ждём событий старше". Engine читает её через ``current_watermark``
и пропагирует в downstream-процессоры через ``Message.watermark``.

Sources без этого Protocol — engine использует hybrid: default = event_time
из ``Message.created_at``.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ("WatermarkEmitter",)


@runtime_checkable
class WatermarkEmitter(Protocol):
    """Источник, эмитящий watermark.

    Methods:
        current_watermark: Текущая граница watermark (wall-clock секунды,
            Unix epoch). ``None`` означает «нет данных» — engine должен
            использовать fallback (event_time).
    """

    def current_watermark(self) -> float | None: ...
