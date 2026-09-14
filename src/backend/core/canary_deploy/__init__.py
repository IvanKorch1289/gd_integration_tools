"""Canary / Shadow Deployment Helper (Wave 4 #76).

Проблема:
    Rollout новой версии route — risk:
    - Один deploy → 100% traffic → катастрофа.
    - Нужно gradual rollout + comparison baseline.
    - Автоматический rollback при regression.

Решение:
    ``CanaryController`` — pure-Python traffic split + metrics:

    1. ``CanaryConfig`` — split (canary%, baseline%, duration).
    2. ``TrafficSplit`` — sticky/non-sticky split by tenant_id hash.
    3. ``MetricsSnapshot`` — record (latency, error_rate, throughput).
    4. ``CanaryDecision`` — promote / rollback / extend.
    5. ``CanaryController.evaluate()`` — compare canary vs baseline.

Использование::

    from src.backend.core.canary_deploy import (
        CanaryController, CanaryConfig, TrafficSplit, get_canary_controller,
    )

    controller = get_canary_controller()
    controller.register(CanaryConfig(
        route_id="order-create", canary_version="v1.2.3",
        baseline_version="v1.2.2", canary_percent=10.0,
    ))

    # Per-request.
    split = controller.get_split("order-create", tenant_id="t1")
    if split == TrafficSplit.CANARY:
        # route через canary.
    else:
        # route через baseline.

    # Per-eval.
    decision = controller.evaluate(
        route_id="order-create",
        canary_metrics=MetricsSnapshot(latency_p99=200, error_rate=0.001),
        baseline_metrics=MetricsSnapshot(latency_p99=200, error_rate=0.001),
    )
"""

from __future__ import annotations

from src.backend.core.canary_deploy.controller import (
    CanaryConfig,
    CanaryController,
    CanaryDecision,
    CanaryVerdict,
    MetricsSnapshot,
    TrafficSplit,
    get_canary_controller,
)

__all__ = (
    "CanaryConfig",
    "CanaryController",
    "CanaryDecision",
    "CanaryVerdict",
    "MetricsSnapshot",
    "TrafficSplit",
    "get_canary_controller",
)
