"""Banking AI processors (S50 W3 decomp).

10 processors + 5 result dataclasses + 1 base class + 1 audit helper.
Decomposed в ``_audit.py`` / ``_base.py`` / ``identity.py`` / ``credit.py`` /
``document.py`` per domain.

Backward-compat: ``from src.backend.dsl.engine.processors.ai_banking import
KycAmlResult, KycAmlVerifyProcessor`` works через re-exports ниже.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.ai_banking._audit import (
    _emit_audit,  # S50 W3: helper
)
from src.backend.dsl.engine.processors.ai_banking._base import (
    _BankingAIProcessor,  # S50 W3: base
)
from src.backend.dsl.engine.processors.ai_banking.credit import (  # S50 W3: re-export
    AppealProcessorAI,
    CreditScoringRagProcessor,
    CreditScoringResult,
    CustomerChatbotProcessor,
)
from src.backend.dsl.engine.processors.ai_banking.document import (  # S50 W3: re-export
    DocumentClassifierProcessor,
    DocumentClassifierResult,
    FinDocOcrLlmProcessor,
    FrancotypingProcessor,
    FrancotypingResult,
    TransactionCategorizerProcessor,
)
from src.backend.dsl.engine.processors.ai_banking.identity import (  # S50 W3: re-export
    AntiFraudResult,
    AntiFraudScoreProcessor,
    KycAmlResult,
    KycAmlVerifyProcessor,
)

__all__ = (
    "_BankingAIProcessor",
    "_emit_audit",
    "AntiFraudResult",
    "AntiFraudScoreProcessor",
    "AppealProcessorAI",
    "CreditScoringResult",
    "CreditScoringRagProcessor",
    "CustomerChatbotProcessor",
    "DocumentClassifierProcessor",
    "DocumentClassifierResult",
    "FinDocOcrLlmProcessor",
    "FrancotypingProcessor",
    "FrancotypingResult",
    "KycAmlResult",
    "KycAmlVerifyProcessor",
    "TransactionCategorizerProcessor",
)
