"""Canary / Shadow Deployment Controller (Wave 4 #76)."""

from __future__ import annotations

import enum
import hashlib
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

__all__ = (
    "CanaryConfig",
    "CanaryController",
    "CanaryDecision",
    "CanaryVerdict",
    "MetricsSnapshot",
    "TrafficSplit",
    "get_canary_controller",
)


class TrafficSplit(str, enum.Enum):
    """Which version a request goes to."""

    BASELINE = "baseline"
    CANARY = "canary"
    SHADOW = "shadow"  # copy only, not affecting user


class CanaryDecision(str, enum.Enum):
    """Decision из canary evaluation."""

    PROMOTE = "promote"  # canary хороший → full rollout
    ROLLBACK = "rollback"  # canary хуже baseline → revert
    EXTEND = "extend"  # неопределённый результат → продлить canary
    PAUSE = "pause"  # остановить rollout (manual decision)


@dataclass(slots=True)
class MetricsSnapshot:
    """Aggregated metrics для comparison."""

    latency_p99_ms: float = 0.0
    error_rate: float = 0.0
    throughput_rps: float = 0.0
    sample_size: int = 0


@dataclass(slots=True)
class CanaryConfig:
    """Canary deployment config.

    Attributes:
        route_id: Affected route.
        canary_version: New version label.
        baseline_version: Existing version label.
        canary_percent: % of traffic to route to canary (0-100).
        max_latency_increase_pct: Max acceptable latency increase (e.g., 20%).
        max_error_rate_increase: Max acceptable error rate absolute increase.
    """

    route_id: str
    canary_version: str
    baseline_version: str
    canary_percent: float = 10.0
    max_latency_increase_pct: float = 20.0
    max_error_rate_increase: float = 0.01  # 1% absolute


@dataclass(slots=True)
class CanaryVerdict:
    """Result of canary vs baseline comparison."""

    decision: CanaryDecision
    latency_delta_pct: float = 0.0
    error_rate_delta: float = 0.0
    reasoning: str = ""


class CanaryController:
    """Canary rollout + shadow comparison controller."""

    def __init__(self) -> None:
        self._configs: dict[str, CanaryConfig] = {}

    @property
    def configs(self) -> list[CanaryConfig]:
        """Все canary-конфигурации (порядок регистрации)."""
        return list(self._configs.values())

    def register(self, config: CanaryConfig) -> None:
        """Зарегистрировать/заменить canary-конфиг по route_id."""
        self._configs[config.route_id] = config

    def unregister(self, route_id: str) -> None:
        """Снять canary с маршрута (unregister)."""
        self._configs.pop(route_id, None)

    def get(self, route_id: str) -> CanaryConfig | None:
        """Получить canary-конфиг маршрута; ``None`` если нет."""
        return self._configs.get(route_id)

    # ─── Traffic split ────────────────────────────────────

    def get_split(self, route_id: str, tenant_id: str | None = None) -> TrafficSplit:
        """Determine which version handles a request.

        Sticky by tenant_id (deterministic hash) для consistent user experience.
        """
        config = self._configs.get(route_id)
        if config is None:
            return TrafficSplit.BASELINE
        if config.canary_percent <= 0:
            return TrafficSplit.BASELINE
        if config.canary_percent >= 100:
            return TrafficSplit.CANARY

        # Sticky by hash.
        if tenant_id is None:
            # No tenant → use canary_percent as probability.
            import random

            return (
                TrafficSplit.CANARY
                if random.random() * 100 < config.canary_percent  # noqa: S311
                else TrafficSplit.BASELINE
            )

        # Hash tenant_id → percentage bucket (MD5 — stable sticky split, not crypto).
        hash_val = int(
            hashlib.md5(tenant_id.encode("utf-8"), usedforsecurity=False).hexdigest(),
            16,
        )
        bucket = (hash_val % 10000) / 100.0  # 0.00 - 99.99
        return (
            TrafficSplit.CANARY
            if bucket < config.canary_percent
            else TrafficSplit.BASELINE
        )

    # ─── Evaluation ─────────────────────────────────────

    def evaluate(
        self,
        route_id: str,
        canary_metrics: MetricsSnapshot,
        baseline_metrics: MetricsSnapshot,
    ) -> CanaryVerdict:
        """Compare canary vs baseline → decision."""
        config = self._configs.get(route_id)
        if config is None:
            return CanaryVerdict(
                decision=CanaryDecision.PROMOTE,
                reasoning="no canary config — default to promote",
            )

        # Sample size check.
        min_samples = 100
        if (
            canary_metrics.sample_size < min_samples
            or baseline_metrics.sample_size < min_samples
        ):
            return CanaryVerdict(
                decision=CanaryDecision.EXTEND,
                reasoning=f"sample size < {min_samples}, extend canary",
            )

        # Latency delta (percent).
        if baseline_metrics.latency_p99_ms > 0:
            latency_delta = (
                (canary_metrics.latency_p99_ms - baseline_metrics.latency_p99_ms)
                / baseline_metrics.latency_p99_ms
                * 100
            )
        else:
            latency_delta = 0.0

        # Error rate delta (absolute).
        error_rate_delta = canary_metrics.error_rate - baseline_metrics.error_rate

        # Latency check.
        if latency_delta > config.max_latency_increase_pct:
            return CanaryVerdict(
                decision=CanaryDecision.ROLLBACK,
                latency_delta_pct=latency_delta,
                error_rate_delta=error_rate_delta,
                reasoning=(
                    f"latency +{latency_delta:.1f}% "
                    f"> {config.max_latency_increase_pct}% threshold"
                ),
            )

        # Error rate check.
        if error_rate_delta > config.max_error_rate_increase:
            return CanaryVerdict(
                decision=CanaryDecision.ROLLBACK,
                latency_delta_pct=latency_delta,
                error_rate_delta=error_rate_delta,
                reasoning=(
                    f"error rate +{error_rate_delta:.2%} "
                    f"> {config.max_error_rate_increase:.2%} threshold"
                ),
            )

        # Canary is good.
        return CanaryVerdict(
            decision=CanaryDecision.PROMOTE,
            latency_delta_pct=latency_delta,
            error_rate_delta=error_rate_delta,
            reasoning=(
                f"canary good: latency delta +{latency_delta:.1f}%, "
                f"error delta +{error_rate_delta:.2%}"
            ),
        )

    def clear(self) -> None:
        """Сбросить все canary-конфигурации (test hook)."""
        self._configs.clear()


_controller: CanaryController | None = None


def get_canary_controller() -> CanaryController:
    """Вернуть process-wide singleton CanaryController (lazy init)."""
    global _controller
    if _controller is None:
        _controller = CanaryController()
    return _controller


def reset_canary_controller() -> None:
    """Сбросить singleton (test isolation)."""
    global _controller
    _controller = None
