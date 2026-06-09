"""AI/ML DSL процессоры — LLM, RAG, PII, prompt composition.

BACKWARDS-COMPAT SHIM (S81 W1, ADR-0102).

Реальные definitions переехали в ``src.backend.dsl.engine.processors.ai.*``
(per-class files: ``cache_processor.py``, ``tokenbudget_processor.py``,
``llmcall_processor.py``, и т.д.). Этот модуль — 1-line shim, re-exporting
из per-class files для backwards compatibility.

S81 W1 = завершение sibling decomp: __init__.py в ``ai/`` package
теперь импортирует из per-class files, не из этого shim. Этот shim
оставлен для backwards-compat со старым import path
(``from src.backend.dsl.engine.processors.ai_processors import ...``).
Удалить в S84+ после deprecation period.

Migration timeline (per ADR-0102):
  S77-S80: sibling created per-class files (15+ files in ai/)
  S81 W1: __init__.py + this shim unified to per-class files
  S84+:    shim удалён, остаётся только per-class import path

Recommended import path (new):
  from src.backend.dsl.engine.processors import CacheProcessor  # через ai/__init__.py
  from src.backend.dsl.engine.processors.ai.cache_processor import CacheProcessor  # direct

Old path (still works через этот shim):
  from src.backend.dsl.engine.processors.ai_processors import CacheProcessor
"""

from src.backend.dsl.engine.processors.ai.cache_processor import CacheProcessor
from src.backend.dsl.engine.processors.ai.cachewrite_processor import (
    CacheWriteProcessor,
)
from src.backend.dsl.engine.processors.ai.getfeedbackexamples_processor import (
    GetFeedbackExamplesProcessor,
)
from src.backend.dsl.engine.processors.ai.guardrails_processor import (
    GuardrailsProcessor,
)
from src.backend.dsl.engine.processors.ai.llmcall_processor import LLMCallProcessor
from src.backend.dsl.engine.processors.ai.llmfallback_processor import (
    LLMFallbackProcessor,
)
from src.backend.dsl.engine.processors.ai.llmparser_processor import LLMParserProcessor
from src.backend.dsl.engine.processors.ai.promptcomposer_processor import (
    PromptComposerProcessor,
)
from src.backend.dsl.engine.processors.ai.ragpiiredaction_processor import (
    RagPIIRedactionProcessor,
)
from src.backend.dsl.engine.processors.ai.ragingest_processor import RagIngestProcessor
from src.backend.dsl.engine.processors.ai.ragquery_processor import RagQueryProcessor
from src.backend.dsl.engine.processors.ai.reranker import RerankerProcessor
from src.backend.dsl.engine.processors.ai.restorepii_processor import (
    RestorePIIProcessor,
)
from src.backend.dsl.engine.processors.ai.sanitizepii_processor import (
    SanitizePIIProcessor,
)
from src.backend.dsl.engine.processors.ai.semanticrouter_processor import (
    SemanticRouterProcessor,
)
from src.backend.dsl.engine.processors.ai.tokenbudget_processor import (
    TokenBudgetProcessor,
)
from src.backend.dsl.engine.processors.ai.vectorsearch_processor import (
    VectorSearchProcessor,
)

__all__ = (
    "CacheProcessor",
    "CacheWriteProcessor",
    "GetFeedbackExamplesProcessor",
    "GuardrailsProcessor",
    "LLMCallProcessor",
    "LLMFallbackProcessor",
    "LLMParserProcessor",
    "PromptComposerProcessor",
    "RagIngestProcessor",
    "RagPIIRedactionProcessor",
    "RagQueryProcessor",
    "RerankerProcessor",
    "RestorePIIProcessor",
    "SanitizePIIProcessor",
    "SemanticRouterProcessor",
    "TokenBudgetProcessor",
    "VectorSearchProcessor",
)
