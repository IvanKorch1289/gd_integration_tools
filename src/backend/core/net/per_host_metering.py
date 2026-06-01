"""Per-host метрики исходящих HTTP-запросов (early-signal для SLA violations).

Назначение:
    Облегчённый in-process счётчик с rolling window для обнаружения
    деградации отдельных upstream-хостов до выхода за пороги SLA.
    Предназначен для ранней сигнализации (early-signal), не для замены
    полноценного observability-стека (Prometheus/OpenTelemetry).

Включение:
    Управляется feature-flag ``feature_flags.metering_per_host`` (default-OFF).
    При выключенном флаге все методы :class:`PerHostMeter` являются no-op —
    без накладных расходов на вычисление персентилей.

Использование::

    from src.backend.core.net.per_host_metering import get_per_host_meter

    meter = get_per_host_meter()
    meter.record("api.example.com", latency_ms=42.0, status_code=200)
    stats = meter.get_stats("api.example.com")
    if stats and stats.error_rate > 0.05:
        ...  # ранняя сигнализация о деградации

Ограничения:
    - rolling window хранит последние 1000 observations на хост;
    - персентили вычисляются наивно (sorted slice) — допустимо при N≤1000;
    - не thread-safe в CPython на уровне asyncio event loop; Lock не нужен,
      так как доступ происходит только из одного потока event loop.
    - Данные сбрасываются при перезапуске процесса (in-memory only).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Final

__all__ = ("HostStats", "PerHostMeter", "get_per_host_meter", "to_prometheus_metrics")

_WINDOW_SIZE: Final[int] = 1000
"""Максимальный размер rolling window на хост (количество observations)."""


@dataclass(slots=True)
class HostStats:
    """Сводная статистика по одному upstream-хосту.

    Атрибуты:
        request_count: Общее число зафиксированных запросов.
        error_count: Число запросов со статусом HTTP >= 500 или сетевой ошибкой
            (status_code <= 0).
        latency_p50_ms: Медиана задержек (50-й персентиль), мс.
        latency_p95_ms: 95-й персентиль задержек, мс.
        last_request_at: Временная метка последнего зафиксированного запроса (UTC).
        error_rate: Доля ошибочных запросов (0.0–1.0).
    """

    request_count: int = 0
    error_count: int = 0
    latency_p50_ms: float = 0.0
    latency_p95_ms: float = 0.0
    last_request_at: datetime | None = None
    error_rate: float = 0.0


@dataclass
class _HostBucket:
    """Внутреннее ведро с сырыми данными для одного хоста.

    Атрибуты:
        latencies: Rolling window задержек в мс (deque с maxlen).
        request_count: Суммарный счётчик запросов.
        error_count: Суммарный счётчик ошибок.
        last_request_at: Время последнего запроса (UTC).
    """

    latencies: deque[float] = field(default_factory=lambda: deque(maxlen=_WINDOW_SIZE))
    request_count: int = 0
    error_count: int = 0
    last_request_at: datetime | None = None

    def record(self, latency_ms: float, status_code: int) -> None:
        """Добавить одно наблюдение в ведро.

        Args:
            latency_ms: Задержка в миллисекундах.
            status_code: HTTP-статус ответа; <=0 означает сетевую ошибку.
        """
        self.latencies.append(latency_ms)
        self.request_count += 1
        if status_code <= 0 or status_code >= 500:
            self.error_count += 1
        self.last_request_at = datetime.now(tz=timezone.utc)

    def to_stats(self) -> HostStats:
        """Вычислить :class:`HostStats` из накопленных данных.

        Returns:
            Снимок текущей статистики хоста.
        """
        if not self.latencies:
            return HostStats(
                request_count=self.request_count,
                error_count=self.error_count,
                last_request_at=self.last_request_at,
            )
        sorted_lat = sorted(self.latencies)
        n = len(sorted_lat)
        p50 = _percentile(sorted_lat, n, 0.50)
        p95 = _percentile(sorted_lat, n, 0.95)
        error_rate = (
            self.error_count / self.request_count if self.request_count else 0.0
        )
        return HostStats(
            request_count=self.request_count,
            error_count=self.error_count,
            latency_p50_ms=round(p50, 3),
            latency_p95_ms=round(p95, 3),
            last_request_at=self.last_request_at,
            error_rate=round(error_rate, 6),
        )


def _percentile(sorted_data: list[float], n: int, q: float) -> float:
    """Вычислить персентиль методом линейной интерполяции (nearest-rank).

    Args:
        sorted_data: Отсортированный список значений.
        n: Длина списка.
        q: Квантиль (0.0–1.0).

    Returns:
        Значение персентиля.
    """
    if n == 1:
        return sorted_data[0]
    idx = q * (n - 1)
    lo = int(math.floor(idx))
    hi = int(math.ceil(idx))
    if lo == hi:
        return sorted_data[lo]
    frac = idx - lo
    return sorted_data[lo] * (1.0 - frac) + sorted_data[hi] * frac


class PerHostMeter:
    """Per-host метрики исходящих HTTP-запросов с rolling window 1000 observations.

    Методы :meth:`record`, :meth:`get_stats`, :meth:`get_all_stats` являются
    no-op при выключенном feature-flag ``metering_per_host``.

    Не предназначен для прямого создания — использовать :func:`get_per_host_meter`.

    Args:
        enabled: Если ``False`` — все операции являются no-op (default-OFF).
    """

    def __init__(self, *, enabled: bool = False) -> None:
        """Инициализировать метер с заданным состоянием флага.

        Args:
            enabled: Активировать запись метрик.
        """
        self._enabled: bool = enabled
        self._buckets: dict[str, _HostBucket] = {}

    def record(self, host: str, latency_ms: float, status_code: int) -> None:
        """Зафиксировать одно наблюдение для хоста.

        При выключенном флаге — no-op без выделения памяти.

        Args:
            host: Имя или IP хоста (без схемы и порта).
            latency_ms: Задержка ответа в миллисекундах.
            status_code: HTTP-статус ответа; <=0 для сетевых ошибок.
        """
        if not self._enabled:
            return
        if host not in self._buckets:
            self._buckets[host] = _HostBucket()
        self._buckets[host].record(latency_ms, status_code)

    def get_stats(self, host: str) -> HostStats | None:
        """Получить статистику для конкретного хоста.

        Args:
            host: Имя хоста.

        Returns:
            :class:`HostStats` или ``None``, если хост не наблюдался или
            флаг выключен.
        """
        if not self._enabled:
            return None
        bucket = self._buckets.get(host)
        if bucket is None:
            return None
        return bucket.to_stats()

    def get_all_stats(self) -> dict[str, HostStats]:
        """Получить статистику по всем наблюдаемым хостам.

        Returns:
            Словарь ``host → HostStats``; пустой при выключенном флаге.
        """
        if not self._enabled:
            return {}
        return {host: bucket.to_stats() for host, bucket in self._buckets.items()}

    def reset(self) -> None:
        """Сбросить все накопленные данные (используется в тестах).

        При выключенном флаге — no-op.
        """
        self._buckets.clear()


# ─── Singleton ────────────────────────────────────────────────────────────────

_meter_instance: PerHostMeter | None = None


def get_per_host_meter() -> PerHostMeter:
    """Вернуть глобальный singleton :class:`PerHostMeter`.

    Состояние флага читается при первом вызове и кешируется.
    Для переинициализации в тестах вызвать :func:`_reset_meter_singleton`.

    Returns:
        Глобальный экземпляр :class:`PerHostMeter`.
    """
    global _meter_instance  # noqa: PLW0603
    if _meter_instance is None:
        from src.backend.core.config.features import feature_flags  # lazy import

        _meter_instance = PerHostMeter(enabled=feature_flags.metering_per_host)
    return _meter_instance


def _reset_meter_singleton() -> None:
    """Сбросить singleton для изоляции тестов.

    Не вызывать в production-коде.
    """
    global _meter_instance  # noqa: PLW0603
    _meter_instance = None


# ─── Prometheus exposition (опционально) ──────────────────────────────────────


def to_prometheus_metrics(meter: PerHostMeter | None = None) -> str:
    """Сформировать строку в формате Prometheus text exposition.

    Используется для экспорта через /metrics endpoint или push-gateway.
    Не добавляет HELP/TYPE заголовки, чтобы агрегировать с другими sources.

    Args:
        meter: Экземпляр :class:`PerHostMeter`; при ``None`` — использует singleton.

    Returns:
        Многострочная строка с метриками в формате ``name{labels} value``.
        Пустая строка, если флаг выключен или данных нет.
    """
    if meter is None:
        meter = get_per_host_meter()
    all_stats = meter.get_all_stats()
    if not all_stats:
        return ""
    lines: list[str] = []
    for host, stats in sorted(all_stats.items()):
        lbl = f'host="{host}"'
        lines.append(f"outbound_request_total{{{lbl}}} {stats.request_count}")
        lines.append(f"outbound_error_total{{{lbl}}} {stats.error_count}")
        lines.append(f"outbound_latency_p50_ms{{{lbl}}} {stats.latency_p50_ms}")
        lines.append(f"outbound_latency_p95_ms{{{lbl}}} {stats.latency_p95_ms}")
        lines.append(f"outbound_error_rate{{{lbl}}} {stats.error_rate}")
    return "\n".join(lines) + "\n"
