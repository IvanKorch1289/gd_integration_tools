from __future__ import annotations
"""Banking AI processors package (S59 W1 decomp from banking_processors.py 552 LOC).

11 classes decomposed в 7 files:
- ``results.py``: 5 Pydantic result schemas
- ``base.py``: _BankingAIProcessor (5 methods, base)
- ``credit.py``, ``fraud.py``, ``risk.py``, ``segmentation.py``, ``loan.py``: 5 concrete processors

Backward-compat: ``from src.backend.dsl.engine.processors.ai.banking_processors import CreditScoreProcessor`` works.
"""


from src.backend.dsl.engine.processors.ai.banking_processors.results import CreditScoreResult  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.results import FraudDetectionResult  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.results import RiskAssessmentResult  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.results import CustomerSegmentationResult  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.results import LoanEligibilityResult  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.base import _BankingAIProcessor  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.credit import CreditScoreProcessor  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.fraud import FraudDetectionProcessor  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.risk import RiskAssessmentProcessor  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.segmentation import CustomerSegmentationProcessor  # S59 W1: re-export
from src.backend.dsl.engine.processors.ai.banking_processors.loan import LoanEligibilityProcessor  # S59 W1: re-export

__all__ = (
    "_BankingAIProcessor",
    "CreditScoreResult",
    "FraudDetectionResult",
    "RiskAssessmentResult",
    "CustomerSegmentationResult",
    "LoanEligibilityResult",
    "CreditScoreProcessor",
    "FraudDetectionProcessor",
    "RiskAssessmentProcessor",
    "CustomerSegmentationProcessor",
    "LoanEligibilityProcessor",
)
