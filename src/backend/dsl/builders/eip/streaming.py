"""Streaming EIP-методы: windowed_dedup / batch / windowed_collect /
tumbling_window / sliding_window / session_window / group_by_key.

Sprint 60 W4 — split из eip.py (1354 LOC).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, cast

from src.backend.core.di.dependencies import get_watermark_store_optional
from src.backend.core.interfaces.watermark_store import WatermarkStore
from src.backend.dsl.builders.eip._base import EIPMixinBase
from src.backend.dsl.engine.processors.streaming import (
    GroupByKeyProcessor,
    SessionWindowProcessor,
    SlidingWindowProcessor,
    TumblingWindowProcessor,
)

if TYPE_CHECKING:
    from src.backend.dsl.builder import RouteBuilder

__all__ = ("StreamingEIPsMixin",)


class StreamingEIPsMixin(EIPMixinBase):
    """Streaming window operations: tumbling / sliding / session / dedup / batch / group_by_key."""

    def windowed_dedup(
        self,
        key_from: str,
        *,
        key_prefix: str = "dedup",
        window_seconds: int = 60,
        mode: str = "first",
    ) -> "RouteBuilder":
        """Дедупликация в скользящем окне с Redis-персистентностью.

        Args:
            key_from: Точечный путь к ключу (напр. ``body.entity_id``).
            key_prefix: Пространство имён Redis-ключей.
            window_seconds: Длительность окна в секундах.
            mode: Режим — ``first`` | ``last`` | ``unique``.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedDedupProcessor,
        )

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                WindowedDedupProcessor(
                    key_from=key_from,
                    key_prefix=key_prefix,
                    window_seconds=window_seconds,
                    mode=mode,
                )
            ),
        )

    def batch(
        self, *, size: int = 100, timeout_ms: int = 500, group_by: str | None = None
    ) -> "RouteBuilder":
        """Накопление сообщений в окно с flush по N ИЛИ по таймауту.

        Args:
            size: Максимальный размер батча перед flush'ем.
            timeout_ms: Таймаут окна в миллисекундах.
            group_by: Опциональный путь группировки. Без значения — общий буфер.
        """
        from src.backend.dsl.engine.processors.patterns import BatchWindowProcessor

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                BatchWindowProcessor(
                    window_seconds=timeout_ms / 1000.0, max_size=size, group_by=group_by
                )
            ),
        )

    def windowed_collect(
        self,
        key_from: str,
        dedup_by: str,
        *,
        window_seconds: int = 60,
        dedup_mode: str = "last",
        inject_as: str = "collected_batch",
    ) -> "RouteBuilder":
        """Накопление и батч-дедупликация сообщений в окне.

        Args:
            key_from: Путь к ключу группировки (напр. ``body.table_name``).
            dedup_by: Путь к полю дедупликации внутри батча.
            window_seconds: Длительность окна в секундах.
            dedup_mode: ``first`` | ``last`` — какое значение сохранять.
            inject_as: Имя exchange-свойства для инжекции батча.
        """
        from src.backend.dsl.engine.processors.eip.windowed_dedup import (
            WindowedCollectProcessor,
        )

        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                WindowedCollectProcessor(
                    key_from=key_from,
                    window_seconds=window_seconds,
                    dedup_by=dedup_by,
                    dedup_mode=dedup_mode,
                    inject_as=inject_as,
                )
            ),
        )

    def tumbling_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        size: int = 100,
        interval_seconds: float = 10.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming tumbling-окно фиксированного размера.

        Если ``watermark_store`` не задан и в ``app.state`` уже
        зарегистрирован durable store, он подхватывается автоматически.
        """
        store = watermark_store or get_watermark_store_optional()
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                TumblingWindowProcessor(
                    sink=sink,
                    size=size,
                    interval_seconds=interval_seconds,
                    watermark_store=store,
                    route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
                )
            ),
        )

    def sliding_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        window_seconds: float = 10.0,
        step_seconds: float = 2.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming sliding-окно с перекрытием."""
        store = watermark_store or get_watermark_store_optional()
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                SlidingWindowProcessor(
                    sink=sink,
                    window_seconds=window_seconds,
                    step_seconds=step_seconds,
                    watermark_store=store,
                    route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
                )
            ),
        )

    def session_window(
        self,
        sink: Callable[[list[Any]], Any],
        *,
        gap_seconds: float = 30.0,
        watermark_store: WatermarkStore | None = None,
    ) -> "RouteBuilder":
        """Streaming session-окно (закрывается по паузе)."""
        store = watermark_store or get_watermark_store_optional()
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                SessionWindowProcessor(
                    sink=sink,
                    gap_seconds=gap_seconds,
                    watermark_store=store,
                    route_id=self.route_id if store is not None else None,  # type: ignore[attr-defined]
                )
            ),
        )

    def group_by_key(
        self,
        key_path: str,
        sink: Callable[[dict[Any, list[Any]]], Any],
        *,
        window_seconds: float = 60.0,
    ) -> "RouteBuilder":
        """Группировка по ключу (jmespath) в пределах окна."""
        return cast(
            "RouteBuilder",
            self._add(  # type: ignore[attr-defined]
                GroupByKeyProcessor(
                    sink=sink, key_path=key_path, window_seconds=window_seconds
                )
            ),
        )
