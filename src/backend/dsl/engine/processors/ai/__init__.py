"""AI processors — reranker, cross-encoder pipeline + banking AI processors.

Re-exports all processors from the per-class files in this package.
Sibling's split (S77+) extracted each class to its own file; S81 W1
completes the migration by switching __init__.py to import from the
per-class files (not from ai_processors.py).
"""

# Banking AI processors
from src.backend.dsl.engine.processors.ai.banking_processors import (
    CreditScoreProcessor,
    CustomerSegmentationProcessor,
    FraudDetectionProcessor,
    LoanEligibilityProcessor,
    RiskAssessmentProcessor,
)

# Per-class AI processors (extracted from ai_processors.py, ADR-0102)
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
from src.backend.dsl.engine.processors.ai.ragingest_processor import RagIngestProcessor
from src.backend.dsl.engine.processors.ai.ragpiiredaction_processor import (
    RagPIIRedactionProcessor,
)
from src.backend.dsl.engine.processors.ai.ragquery_processor import RagQueryProcessor

# Reranker processor (separately added in sibling split)
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
    "CreditScoreProcessor",
    "CustomerSegmentationProcessor",
    "FraudDetectionProcessor",
    "GetFeedbackExamplesProcessor",
    "GuardrailsProcessor",
    "LLMCallProcessor",
    "LLMFallbackProcessor",
    "LLMParserProcessor",
    "LoanEligibilityProcessor",
    "PromptComposerProcessor",
    "RagIngestProcessor",
    "RagPIIRedactionProcessor",
    "RagQueryProcessor",
    "RerankerProcessor",
    "RestorePIIProcessor",
    "RiskAssessmentProcessor",
    "SanitizePIIProcessor",
    "SemanticRouterProcessor",
    "TokenBudgetProcessor",
    "VectorSearchProcessor",
)
