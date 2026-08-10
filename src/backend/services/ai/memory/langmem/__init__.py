"""LangMem hierarchical memory модули (Wave D.6 + Stream E.7).

Экспортирует:
- ConsolidationEngine / RLMFeedbackProcessor — consolidation pipeline (Wave D.6).
- EpisodicMemory / SemanticMemory / ProceduralMemory — split memory tier
  CRUD-операции поверх Postgres (Stream E.7 Sprint 8 K4 W2).
"""

from src.backend.services.ai.memory.langmem.consolidation import (
    ConsolidationEngine,
    ConsolidationReport,
)
from src.backend.services.ai.memory.langmem.episodic import EpisodicMemory  # noqa: F401 — re-export
from src.backend.services.ai.memory.langmem.procedural import ProceduralMemory  # noqa: F401 — re-export
from src.backend.services.ai.memory.langmem.rlm import RLMFeedbackProcessor  # noqa: F401 — re-export
from src.backend.services.ai.memory.langmem.semantic import SemanticMemory  # noqa: F401 — re-export

__all__ = (
    "ConsolidationEngine",
    "ConsolidationReport",
    "EpisodicMemory",
    "ProceduralMemory",
    "RLMFeedbackProcessor",
    "SemanticMemory",
)
