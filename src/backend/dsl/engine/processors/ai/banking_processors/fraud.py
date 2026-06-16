"""S59 W1 — fraud.py part of banking_processors decomp.

Classes: FraudDetectionProcessor.

Fraud detection processor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.ai.banking_processors.base import (
    _BankingAIProcessor,  # S59 W1: base for processors
)
from src.backend.dsl.engine.processors.ai.banking_processors.results import (
    FraudDetectionResult,  # S59 W1: result schema
)

if TYPE_CHECKING:
    pass

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class FraudDetectionProcessor(_BankingAIProcessor):
    """Детекция фрода — анализ транзакции на признаки мошенничества.

    Вход (body):
        transaction_amount: float — сумма транзакции
        transaction_type: str — тип (card_present, online, wire, etc.)
        merchant_category: str — категория мерчанта (MCC)
        location: str — локация транзакции
        account_age_days: int — возраст аккаунта в днях
        recent_transactions: int — количество транзакций за последние 24ч

    Выход (body.frauddetection):
        fraud_score: float (0.0-1.0) — вероятность фрода
        is_suspicious: bool — флаг подозрительности
        fraud_indicators: list[str] — найденные индикаторы фрода
        recommended_action: str — allow / block / review

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = FraudDetectionResult

    prompt_template = """Проанализируй транзакцию на признаки мошенничества.

Данные транзакции:
- сумма: ${body.transaction_amount}
- тип: ${body.transaction_type}
- категория мерчанта: ${body.merchant_category}
- локация: ${body.location}
- возраст аккаунта: ${body.account_age_days} дней
- транзакций за 24ч: ${body.recent_transactions}

Верни JSON со следующими полями:
- fraud_score: float (0.0-1.0) — вероятность фрода
- is_suspicious: bool — True если fraud_score > 0.7
- fraud_indicators: list[str] — список найденных индикаторов фрода
- recommended_action: str — "allow" если score < 0.3, "review" если 0.3-0.7, "block" если > 0.7

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""
