"""Shadow Route / Canary Validation Helper (Wave 4 #51).

Проблема (DEEP_AUDIT):
    Rollout новой версии route — risk:
    - Полный rollout → 100% traffic.
    - Нет способа shadow-evaluate (новый route в parallel).
    - Нет comparator'а (результаты разошлись — что делать?).

Решение:
    ``ShadowRouter`` — pure-Python shadow + comparator:

    1. ``ShadowResult`` — результат shadow execution.
    2. ``ComparisonRule`` — правило сравнения (equals, subset, threshold).
    3. ``ShadowComparator`` — execute baseline + shadow, compare.
    4. ``TrafficMirror`` — sticky by tenant_id (consistent user experience).

Использование::

    from src.backend.core.shadow_route import (
        ShadowRouter, ShadowResult, ComparisonRule, ComparisonType,
        get_shadow_router,
    )

    router = get_shadow_router()
    router.add_baseline("order-create", "v1.2.2", baseline_fn)
    router.add_shadow("order-create", "v1.2.3", shadow_fn)

    # Mirror by tenant_id (consistent UX).
    if router.should_mirror("order-create", tenant_id="t1"):
        shadow_result = router.run_shadow("order-create", "v1.2.3", payload)

    # Compare results.
    rule = ComparisonRule(type=ComparisonType.APPROX_EQUAL, tolerance=0.01)
    comparison = router.compare(baseline_result, shadow_result, rule)
"""

from __future__ import annotations

from src.backend.core.shadow_route.comparator import (
    ComparisonOutcome,
    ComparisonRule,
    ComparisonType,
    ShadowComparator,
    ShadowResult,
    ShadowRouter,
    get_shadow_router,
)

__all__ = (
    "ComparisonOutcome",
    "ComparisonRule",
    "ComparisonType",
    "ShadowComparator",
    "ShadowResult",
    "ShadowRouter",
    "get_shadow_router",
)
