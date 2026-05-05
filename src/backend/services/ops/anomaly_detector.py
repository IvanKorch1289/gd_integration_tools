"""Anomaly Detection — обнаружение отклонений в метриках.

Методы:
- Rolling mean + std dev (Z-score > 3 = аномалия)
- Sudden spike в queue depth
- Error rate выше threshold

При обнаружении → уведомление через NotificationHub в eXpress.
"""

from __future__ import annotations

import logging
import statistics
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.di.app_state import app_state_singleton

__all__ = ("AnomalyDetector", "Anomaly", "get_anomaly_detector")

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Anomaly:
    metric: str
    value: float
    mean: float
    stddev: float
    z_score: float
    severity: str  # "warning" | "critical"
    context: dict[str, Any] = field(default_factory=dict)


class AnomalyDetector:
    """Детектор аномалий по rolling window."""

    def __init__(self, window_size: int = 100, z_threshold: float = 3.0) -> None:
        self._window = window_size
        self._z_threshold = z_threshold
        self._series: dict[str, deque[float]] = {}
        self._notification_channels: list[dict[str, Any]] = []

    def set_notification_channels(self, channels: list[dict[str, Any]]) -> None:
        """Задаёт куда слать алерты при аномалии.

        channels:
            [{"channel": "express", "to": "chat-uuid"},
             {"channel": "email", "to": "ops@bank.ru"}]
        """
        self._notification_channels = channels

    async def observe(self, metric: str, value: float) -> Anomaly | None:
        """Регистрирует значение, проверяет на аномалию.

        Returns:
            Anomaly если обнаружена, иначе None.
        """
        if metric not in self._series:
            self._series[metric] = deque(maxlen=self._window)

        series = self._series[metric]
        # Нужно минимум 10 наблюдений для статистики
        if len(series) < 10:
            series.append(value)
            return None

        mean = statistics.mean(series)
        stddev = statistics.stdev(series) if len(series) > 1 else 0.0

        if stddev == 0:
            series.append(value)
            return None

        z_score = (value - mean) / stddev
        abs_z = abs(z_score)

        series.append(value)

        if abs_z >= self._z_threshold:
            severity = "critical" if abs_z >= 5.0 else "warning"
            anomaly = Anomaly(
                metric=metric,
                value=value,
                mean=mean,
                stddev=stddev,
                z_score=z_score,
                severity=severity,
            )
            await self._notify(anomaly)
            logger.warning(
                "Anomaly detected: %s value=%.2f (z=%.2f, severity=%s)",
                metric,
                value,
                z_score,
                severity,
            )
            return anomaly

        return None

    async def _notify(self, anomaly: Anomaly) -> None:
        """Отправляет алерт об аномалии."""
        if not self._notification_channels:
            return

        try:
            from src.backend.services.ops.notification_hub import get_notification_hub

            hub = get_notification_hub()
            subject = f"[{anomaly.severity.upper()}] Anomaly: {anomaly.metric}"
            message = (
                f"Метрика: {anomaly.metric}\n"
                f"Значение: {anomaly.value:.2f}\n"
                f"Среднее: {anomaly.mean:.2f}\n"
                f"Z-score: {anomaly.z_score:.2f}\n"
                f"Stddev: {anomaly.stddev:.2f}"
            )
            await hub.broadcast(
                channels=self._notification_channels, subject=subject, message=message
            )
        except Exception as exc:
            logger.error("Anomaly notification failed: %s", exc)

    def get_stats(self, metric: str) -> dict[str, Any]:
        """Возвращает статистику по метрике."""
        if metric not in self._series or not self._series[metric]:
            return {"metric": metric, "samples": 0}

        series = self._series[metric]
        return {
            "metric": metric,
            "samples": len(series),
            "mean": statistics.mean(series),
            "stddev": statistics.stdev(series) if len(series) > 1 else 0.0,
            "min": min(series),
            "max": max(series),
        }

    def list_metrics(self) -> list[str]:
        return list(self._series.keys())


@app_state_singleton("anomaly_detector", factory=AnomalyDetector)
def get_anomaly_detector() -> AnomalyDetector:
    raise NotImplementedError  # заменяется декоратором
