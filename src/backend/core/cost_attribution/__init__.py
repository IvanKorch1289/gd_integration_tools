"""Cost Attribution — per-route/tenant/agent cost tracking (Wave 4 #75).

Проблема:
    Нет visibility в cost per route / connector / tenant:
    - Сколько стоит order processing в месяц?
    - Какой tenant потребляет больше всего LLM tokens?
    - Какой external connector (Skb, Dadata) — самый дорогой?

Решение:
    ``CostAttribution`` — pure-Python decorator + registry:

    1. ``CostRecord`` — единичная запись cost event.
    2. ``CostRegistry`` — accumulate records per (tenant, route, agent).
    3. ``@track_cost(resource_type, cost_calculator)`` — decorator для auto-tracking.
    4. ``CostReport`` — aggregation (by tenant / by route / by resource).
    5. Pure-Python — без external dependencies, in-memory storage.

Использование::

    from src.backend.core.cost_attribution import track_cost, get_cost_registry

    @track_cost(resource_type="llm_tokens", cost_per_unit=0.0001)
    async def call_llm(prompt):
        tokens = await _count_tokens(prompt)
        return await _openai_call(prompt), tokens

    # After running — query.
    registry = get_cost_registry()
    report = registry.generate_report()
    print(report.total_cost_usd)
    print(report.by_tenant())
"""

from __future__ import annotations

from src.backend.core.cost_attribution.attribution import (
    CostAttribution,
    CostRecord,
    CostReport,
    ResourceType,
    get_cost_attribution,
    get_cost_registry,
    reset_cost_attribution,
    track_cost,
)

__all__ = (
    "CostAttribution",
    "CostRecord",
    "CostReport",
    "ResourceType",
    "get_cost_attribution",
    "get_cost_registry",
    "reset_cost_attribution",
    "track_cost",
)
