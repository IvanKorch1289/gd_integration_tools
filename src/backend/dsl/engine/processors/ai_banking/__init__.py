"""Banking AI processors (S50 W3 decomp).

10 processors + 5 result dataclasses + 1 base class + 1 audit helper.
Decomposed в ``_audit.py`` / ``_base.py`` / ``identity.py`` / ``credit.py`` /
``document.py`` per domain.

Backward-compat: ``from src.backend.dsl.engine.processors.ai_banking import
KycAmlResult, KycAmlVerifyProcessor`` works через re-exports ниже.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.ai_banking._base import (  # noqa: F401 — re-export
    _BankingAIProcessor,  # S50 W3: base
)
from src.backend.dsl.engine.processors.ai_banking.credit import (  # noqa: F401 — re-export  # S50 W3: re-export
    AppealProcessorAI,
    CreditScoringRagProcessor,
    CreditScoringResult,
    CustomerChatbotProcessor,
)
from src.backend.dsl.engine.processors.ai_banking.document import (  # noqa: F401 — re-export  # S50 W3: re-export
    DocumentClassifierProcessor,
    DocumentClassifierResult,
    FinDocOcrLlmProcessor,
    FrancotypingProcessor,
    FrancotypingResult,
    TransactionCategorizerProcessor,
)
from src.backend.dsl.engine.processors.ai_banking.identity import (  # noqa: F401 — re-export  # S50 W3: re-export
    AntiFraudResult,
    AntiFraudScoreProcessor,
    KycAmlResult,
    KycAmlVerifyProcessor,
)
from src.backend.dsl.engine.processors.ai_banking.loan import (  # noqa: F401 — re-export  # B3: migrated from S59
    LoanEligibilityProcessor,
    LoanEligibilityResult,
)
from src.backend.dsl.engine.processors.ai_banking.risk import (  # noqa: F401 — re-export  # B3: migrated from S59
    RiskAssessmentProcessor,
    RiskAssessmentResult,
)
from src.backend.dsl.engine.processors.ai_banking.segmentation import (  # noqa: F401 — re-export  # B3: migrated from S59
    CustomerSegmentationProcessor,
    CustomerSegmentationResult,
)

__all__ = (
    "AntiFraudResult",
    "AntiFraudScoreProcessor",
    "AppealProcessorAI",
    "CreditScoringRagProcessor",
    "CreditScoringResult",
    "CustomerChatbotProcessor",
    "CustomerSegmentationProcessor",
    "CustomerSegmentationResult",
    "DocumentClassifierProcessor",
    "DocumentClassifierResult",
    "FinDocOcrLlmProcessor",
    "FrancotypingProcessor",
    "FrancotypingResult",
    "KycAmlResult",
    "KycAmlVerifyProcessor",
    "LoanEligibilityProcessor",
    "LoanEligibilityResult",
    "RiskAssessmentProcessor",
    "RiskAssessmentResult",
    "TransactionCategorizerProcessor",
    "_BankingAIProcessor",
)
