"""S59 W1 — segmentation.py part of banking_processors decomp.

Classes: CustomerSegmentationProcessor.

Customer segmentation processor.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.ai.banking_processors.base import (
    _BankingAIProcessor,  # S59 W1: base for processors
)
from src.backend.dsl.engine.processors.ai.banking_processors.results import (
    CustomerSegmentationResult,  # S59 W1: result schema
)

if TYPE_CHECKING:
    pass

_logger = get_logger("dsl.processors.ai.banking")

# ─── Pydantic schemas for structured output ─────────────────────────────────


class CustomerSegmentationProcessor(_BankingAIProcessor):
    """Сегментация клиентов — отнесение клиента к банковскому сегменту.

    Вход (body):
        demographics: str — демографические данные
        account_activity: str — активность по счетам (свободный текст)
        product_holdings: str — текущие продукты клиента
        channel_preference: str — предпочитаемый канал взаимодействия

    Выход (body.customersegmentation):
        segment: str — mass / affluent / business / vip / new
        confidence: float (0.0-1.0) — уверенность в сегментации
        characteristics: list[str] — характеристики сегмента
        recommended_products: list[str] — рекомендованные продукты

    Feature flag: ``feature_flags.banking_ai_processors_enabled`` (default-OFF).
    """

    ResultSchema = CustomerSegmentationResult

    prompt_template = """Определи сегмент клиента и порекомендуй продукты.

Данные клиента:
- демография: ${body.demographics}
- активность: ${body.account_activity}
- текущие продукты: ${body.product_holdings}
- предпочитаемый канал: ${body.channel_preference}

Верни JSON со следующими полями:
- segment: str — "mass" (обычные клиенты), "affluent" (состоятельные), "business" (бизнес), "vip" (премиум), "new" (новые)
- confidence: float (0.0-1.0) — уверенность в определении сегмента
- characteristics: list[str] — 2-3 характеристики определённого сегмента
- recommended_products: list[str] — 2-3 рекомендованных продукта для этого сегмента

Отвечай ТОЛЬКО валидным JSON, соответствующим схеме."""
