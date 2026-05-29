"""AI processors — reranker, cross-encoder pipeline + banking AI processors.

Re-exports all processors from ai_processors.py for backward compatibility,
plus the new RerankerProcessor and banking AI processors.
"""

# Original AI processors from ai_processors.py (sibling file)
from src.backend.dsl.engine.processors.ai_processors import (
    CacheProcessor,
    CacheWriteProcessor,
    GetFeedbackExamplesProcessor,
    GuardrailsProcessor,
    LLMCallProcessor,
    LLMFallbackProcessor,
    LLMParserProcessor,
    PromptComposerProcessor,
    RagIngestProcessor,
    RagPIIRedactionProcessor,
    RagQueryProcessor,
    RestorePIIProcessor,
    SanitizePIIProcessor,
    SemanticRouterProcessor,
    TokenBudgetProcessor,
    VectorSearchProcessor,
)

# Reranker processor
from src.backend.dsl.engine.processors.ai.reranker import RerankerProcessor

# Banking AI processors
from src.backend.dsl.engine.processors.ai.banking_processors import (
    CreditScoreProcessor,
    CustomerSegmentationProcessor,
    FraudDetectionProcessor,
    LoanEligibilityProcessor,
    RiskAssessmentProcessor,
)

__all__ = (
    # From ai_processors.py
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
    "RestorePIIProcessor",
    "SanitizePIIProcessor",
    "SemanticRouterProcessor",
    "TokenBudgetProcessor",
    "VectorSearchProcessor",
    # From reranker.py
    "RerankerProcessor",
    # Banking AI processors
    "CreditScoreProcessor",
    "CustomerSegmentationProcessor",
    "FraudDetectionProcessor",
    "LoanEligibilityProcessor",
    "RiskAssessmentProcessor",
)
