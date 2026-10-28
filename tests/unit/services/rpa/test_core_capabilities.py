"""Baseline-декларации capability ядра (ADR-0370, cycle 172).

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
"""

from __future__ import annotations

from src.backend.core.security.capabilities import build_default_vocabulary
from src.backend.core.security.capabilities.core_declarations import (
    CORE_CAPABILITIES,
    core_capability_refs,
)

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
    """core_capability_refs() отдаёт декларации для всех 4 capability."""
    declared = {ref.name for ref in core_capability_refs()}
    missing = sorted(set(REQUIRED) - declared)
    assert not missing, f"нет CapabilityRef для: {missing}"
