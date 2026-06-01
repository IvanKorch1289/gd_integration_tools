"""Reference Inspect AI suites (K4 S6 W1).

Содержит 7 эталонных suite для регулярной nightly оценки качества
LLM-цепочек проекта: knowledge_qa, instruction_following, hallucination,
safety, context_recall, tool_use, multi_turn_coherence.
"""

from __future__ import annotations

from src.backend.services.ai.eval.suites.context_recall import context_recall_suite
from src.backend.services.ai.eval.suites.hallucination_check import (
    hallucination_check_suite,
)
from src.backend.services.ai.eval.suites.instruction_following import (
    instruction_following_suite,
)
from src.backend.services.ai.eval.suites.knowledge_qa import knowledge_qa_suite
from src.backend.services.ai.eval.suites.multi_turn_coherence import (
    multi_turn_coherence_suite,
)
from src.backend.services.ai.eval.suites.safety_classifier import (
    safety_classifier_suite,
)
from src.backend.services.ai.eval.suites.tool_use import tool_use_suite

REFERENCE_SUITES = (
    knowledge_qa_suite,
    instruction_following_suite,
    hallucination_check_suite,
    safety_classifier_suite,
    context_recall_suite,
    tool_use_suite,
    multi_turn_coherence_suite,
)

__all__ = ("REFERENCE_SUITES",)
