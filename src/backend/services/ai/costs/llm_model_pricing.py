"""LLM Model Pricing registry — Sprint 12 K4 W2.

Источник цен на LLM-токены для cost estimation (per 1K tokens):

* OpenAI (gpt-4o, gpt-4o-mini);
* Anthropic Claude (sonnet-4-6, opus-4-7, haiku-4-5);
* OSS-модели (Llama 3.x, Qwen) — нулевая стоимость по API, только
  compute (учитывается отдельно).

Цены deterministic и хранятся в Decimal. Если модель отсутствует в
registry, используется default price ``$0.002 / 1K tokens`` (как
gpt-4o-mini base).

API:
    * :class:`LLMModelPricing.get_price(model_id) -> Decimal`;
    * :class:`LLMModelPricing.list_known() -> Sequence[str]`.

Override через env vars: ``LLM_PRICE_<MODEL_ID>=0.005`` (заменяет
default).
"""

from __future__ import annotations

import os
from decimal import Decimal

__all__ = ("LLMModelPricing",)


_DEFAULT_PRICE = Decimal("0.002")


_PRICING_USD_PER_1K_TOKENS: dict[str, Decimal] = {
    # OpenAI (по состоянию на 2026-05)
    "gpt-4o": Decimal("0.005"),
    "gpt-4o-mini": Decimal("0.00015"),
    "o1-preview": Decimal("0.015"),
    "o1-mini": Decimal("0.003"),
    "o3-mini": Decimal("0.002"),
    # Anthropic Claude 4.x
    "claude-opus-4-7": Decimal("0.015"),
    "claude-opus-4-6": Decimal("0.015"),
    "claude-sonnet-4-6": Decimal("0.003"),
    "claude-sonnet-4-5": Decimal("0.003"),
    "claude-haiku-4-5-20251001": Decimal("0.0008"),
    "claude-haiku-4-5": Decimal("0.0008"),
    # OSS / self-hosted (compute-only)
    "llama-3.3-70b": Decimal("0"),
    "qwen-2.5-72b": Decimal("0"),
    "bge-m3": Decimal("0"),
}


class LLMModelPricing:
    """LLM pricing registry с env override."""

    def __init__(self) -> None:
        self._cache: dict[str, Decimal] = dict(_PRICING_USD_PER_1K_TOKENS)
        self._apply_env_overrides()

    def _apply_env_overrides(self) -> None:
        """Подменяет цены из env vars ``LLM_PRICE_<MODEL_ID>``."""
        for key, value in os.environ.items():
            if not key.startswith("LLM_PRICE_"):
                continue
            model_id = key.removeprefix("LLM_PRICE_").lower().replace("_", "-")
            try:
                self._cache[model_id] = Decimal(value)
            except (ValueError, ArithmeticError):
                continue

    def get_price(self, model_id: str) -> Decimal:
        """Возвращает цену за 1K tokens. Default при отсутствии модели."""
        if not model_id:
            return _DEFAULT_PRICE
        normalized = model_id.lower().strip()
        return self._cache.get(normalized, _DEFAULT_PRICE)

    def list_known(self) -> list[str]:
        """Список известных моделей в registry."""
        return sorted(self._cache.keys())
