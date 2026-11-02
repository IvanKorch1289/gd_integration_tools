"""Baseline-декларации capability ядра (ADR-0370, cycle 172; ADR-0416).

``CORE_CAPABILITIES`` — набор capability, которые core-процессоры DSL
декларируют в process-wide singleton-гейте. Cycle 172 (решение владельца)
в нём не хватало 4 capability, которые реально используются процессорами
и уже присутствуют в vocabulary:

* ``web_search.perplexity.invoke`` — web_search-процессор;
* ``web_search.tavily.invoke`` — web_search-процессор;
* ``workflow.claim_check.store`` — WorkflowClaimCheckProcessor;
* ``workflow.continue_as_new.request`` — workflow-процессор.

Без декларации capability не проходит ``CapabilityGate`` (fail-closed) —
то есть процессор в рантайме получает blanket-deny.

ADR-0416: механизм покрытия изменился. Resource-scoped capability
(``workflow.claim_check.store`` — scope = идентификатор workflow'а) в
baseline-декларацию гейта **не** входят: blanket ``scope="**"`` отключал
scope-проверку. Их объявляет владелец ресурса, а ядро выдаёт capability
через **core-baseline** — явным флагом
``dsl_capability_core_baseline_enabled`` (ADR-0366 §2).
"""

from __future__ import annotations

import pytest

from src.backend.core.security.capabilities import build_default_vocabulary
from src.backend.core.security.capabilities.core_declarations import (
    CORE_CAPABILITIES,
    RESOURCE_SCOPED_CAPABILITIES,
    core_capability_refs,
)
from src.backend.core.security.capabilities.gate import get_capability_gate
from src.backend.core.security.capabilities.runtime_resolver import (
    CapabilityRequest,
    check,
)

pytestmark = pytest.mark.unit

#: Capability, которые обязаны быть в baseline-декларации ядра.
REQUIRED: tuple[str, ...] = (
    "web_search.perplexity.invoke",
    "web_search.tavily.invoke",
    "workflow.claim_check.store",
    "workflow.continue_as_new.request",
)


def test_required_capabilities_declared() -> None:
    """Все 4 capability объявлены в CORE_CAPABILITIES."""
    missing = sorted(set(REQUIRED) - set(CORE_CAPABILITIES))
    assert not missing, f"не объявлены в CORE_CAPABILITIES: {missing}"


def test_required_capabilities_in_vocabulary() -> None:
    """Каждая из 4 capability есть в vocabulary (иначе gate её не знает)."""
    names = {definition.name for definition in build_default_vocabulary().all()}
    missing = sorted(set(REQUIRED) - names)
    assert not missing, f"отсутствуют в vocabulary: {missing}"


def test_core_capabilities_subset_of_vocabulary() -> None:
    """Ни одна объявленная capability не отсутствует в vocabulary."""
    names = {definition.name for definition in build_default_vocabulary().all()}
    unknown = sorted(set(CORE_CAPABILITIES) - names)
    assert not unknown, f"CORE_CAPABILITIES содержит неизвестные capability: {unknown}"


def test_core_capability_refs_cover_required() -> None:
    """Требуемые capability покрыты baseline-декларациями ядра.

    ADR-0416: resource-scoped capability в baseline-декларацию **не**
    входят — их объявляет владелец ресурса. Покрытие обеспечивает
    core-baseline в runtime-резолвере (проверяется отдельным тестом
    ``test_required_capabilities_granted_by_core_baseline``).
    """
    declared = {ref.name for ref in core_capability_refs()}
    leaked = sorted(set(REQUIRED) & RESOURCE_SCOPED_CAPABILITIES)
    assert not (declared & set(leaked)), f"resource-scoped capability в baseline: {leaked}"


def test_required_capabilities_granted_by_core_baseline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """С флагом baseline требуемые capability выдаются ядром (ADR-0366 §2)."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "dsl_capability_core_baseline_enabled", True)
    get_capability_gate.cache_clear()
    try:
        gate = get_capability_gate()
        for capability in REQUIRED:
            decision = check(
                CapabilityRequest(
                    capability=capability, plugin="core", tenant="tenant-1"
                ),
                gate=gate,
            )
            assert decision.allowed is True, f"{capability}: {decision.reason}"
            assert decision.reason == "core_baseline"
    finally:
        get_capability_gate.cache_clear()
