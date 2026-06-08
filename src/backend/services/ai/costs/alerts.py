"""CostAlertService — двухоконный mean+2σ детектор аномалий (Wave D.5).

Сравниваем текущее окно (last ``window``) с предыдущим окном такой же
длительности. Если разница ``cost_current`` − ``mean(prev)`` > 2σ —
сообщаем alert.

Минимальный sample size — настраивается параметром (default 20),
чтобы не падать на шумных малых выборках.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from src.backend.infrastructure.logging.factory import get_logger
from src.backend.services.ai.costs.langfuse_reader import CostRow, LangFuseReader

logger = get_logger(__name__)

__all__ = ("CostAlert", "CostAlertService")


@dataclass(slots=True)
class CostAlert:
    """Запись об обнаруженной аномалии."""

    key: str
    current_cost_usd: float
    previous_mean_usd: float
    previous_std_usd: float
    samples: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "current_cost_usd": round(self.current_cost_usd, 6),
            "previous_mean_usd": round(self.previous_mean_usd, 6),
            "previous_std_usd": round(self.previous_std_usd, 6),
            "samples": self.samples,
        }


class CostAlertService:
    """Детектор аномалий стоимости поверх LangFuseReader."""

    def __init__(
        self,
        reader: LangFuseReader | None = None,
        *,
        z_threshold: float = 2.0,
        min_samples: int = 20,
    ) -> None:
        self._reader = reader or LangFuseReader()
        self._z = float(z_threshold)
        self._min_samples = int(min_samples)

    async def detect_anomalies(
        self,
        *,
        window: timedelta = timedelta(hours=1),
        group_by: Literal["route", "tenant", "provider"] = "route",
        top_n: int = 50,
    ) -> list[CostAlert]:
        """Сравнивает текущее окно ``window`` с предшествующим ``window``.

        Args:
            window: длительность одного окна.
            group_by: ключ группировки cost-таблицы.
            top_n: размер топа для анализа.
        """
        current = await self._reader.fetch_costs(
            window=window, group_by=group_by, top_n=top_n
        )
        previous = await self._reader.fetch_costs(
            window=window * 2, group_by=group_by, top_n=top_n
        )

        prev_index = {r.key: r for r in previous}
        prev_total_requests = sum(r.requests for r in previous)
        if prev_total_requests < self._min_samples:
            logger.debug(
                "Cost alerts skipped: too few samples (%d < %d)",
                prev_total_requests,
                self._min_samples,
            )
            return []

        alerts: list[CostAlert] = []
        for current_row in current:
            previous_row = prev_index.get(current_row.key)
            if previous_row is None:
                continue
            mean, std = _basic_stats(previous, attr="total_cost_usd")
            if std <= 0:
                continue
            z = (current_row.total_cost_usd - mean) / std
            if z >= self._z:
                alerts.append(
                    CostAlert(
                        key=current_row.key,
                        current_cost_usd=current_row.total_cost_usd,
                        previous_mean_usd=mean,
                        previous_std_usd=std,
                        samples=prev_total_requests,
                    )
                )
        return alerts


def _basic_stats(rows: list[CostRow], *, attr: str) -> tuple[float, float]:
    """Среднее и стандартное отклонение (population) по атрибуту строки."""
    if not rows:
        return 0.0, 0.0
    values = [float(getattr(r, attr, 0.0) or 0.0) for r in rows]
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    return mean, math.sqrt(var)
