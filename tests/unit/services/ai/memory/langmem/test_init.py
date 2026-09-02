"""Unit-тесты ``services.ai.memory.langmem`` — coverage ratchet (Post-Plan A Sprint 17).

core/ai/memory/langmem subpackage (Wave D.6 + Stream E.7): re-exports
6 symbols (ConsolidationEngine + ConsolidationReport + EpisodicMemory +
ProceduralMemory + RLMFeedbackProcessor + SemanticMemory). ~10 stmts, 0%.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai.memory import langmem
from src.backend.services.ai.memory.langmem import (
    ConsolidationEngine,
    ConsolidationReport,
    EpisodicMemory,
    ProceduralMemory,
    RLMFeedbackProcessor,
    SemanticMemory,
)


@pytest.mark.unit
class TestLangmemFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ConsolidationEngine",
            "ConsolidationReport",
            "EpisodicMemory",
            "ProceduralMemory",
            "RLMFeedbackProcessor",
            "SemanticMemory",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(langmem, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in langmem.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 6 символов."""
        assert len(langmem.__all__) == 6

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает LangMem hierarchical memory."""
        assert langmem.__doc__ is not None
        assert "LangMem" in langmem.__doc__ or "memory" in langmem.__doc__.lower()


@pytest.mark.unit
class TestLangmemFacadeIdentity:
    """Identity checks для 6 re-exports."""

    def test_consolidation_engine_is_class(self) -> None:
        """``ConsolidationEngine`` — class (consolidation pipeline)."""
        assert isinstance(ConsolidationEngine, type)

    def test_consolidation_report_is_class(self) -> None:
        """``ConsolidationReport`` — class (report dataclass)."""
        assert isinstance(ConsolidationReport, type)

    def test_episodic_memory_is_class(self) -> None:
        """``EpisodicMemory`` — class (episodic memory tier)."""
        assert isinstance(EpisodicMemory, type)

    def test_procedural_memory_is_class(self) -> None:
        """``ProceduralMemory`` — class (procedural memory tier)."""
        assert isinstance(ProceduralMemory, type)

    def test_rlm_feedback_processor_is_class(self) -> None:
        """``RLMFeedbackProcessor`` — class (RLM feedback processor)."""
        assert isinstance(RLMFeedbackProcessor, type)

    def test_semantic_memory_is_class(self) -> None:
        """``SemanticMemory`` — class (semantic memory tier)."""
        assert isinstance(SemanticMemory, type)
