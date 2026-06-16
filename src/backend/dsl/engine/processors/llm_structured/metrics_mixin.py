from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    pass

_logger = get_logger(__name__)

# Дефолтный ``temperature`` для structured-output: детерминизм важнее
# креативности при заполнении схемы.
_DEFAULT_TEMPERATURE: float = 0.0
# Максимальное число instructor-retries (внутренний цикл валидации Pydantic).
_DEFAULT_RETRY: int = 3


class MetricsMixin:
    """cost estimation + token extraction для LLMStructuredProcessor. S65 W2 extraction."""

    __slots__ = ()

    @staticmethod
    def _estimate_cost(raw_response: Any) -> float | None:
        """Оценивает стоимость через ``litellm.completion_cost``.

        Args:
            raw_response: Ответ от ``litellm.acompletion`` или ``None``.

        Returns:
            Стоимость в USD, ``None`` если оценка недоступна.
        """
        if raw_response is None:
            return None
        try:
            import litellm

            cost = litellm.completion_cost(completion_response=raw_response)
            return float(cost) if cost is not None else None
        except ImportError, AttributeError, TypeError, ValueError:
            return None

    @staticmethod
    def _extract_tokens(raw_response: Any) -> int | None:
        """Извлекает total_tokens из usage."""
        if raw_response is None:
            return None
        usage = getattr(raw_response, "usage", None)
        if usage is None and isinstance(raw_response, dict):
            usage = raw_response.get("usage")
        if usage is None:
            return None
        total = getattr(usage, "total_tokens", None)
        if total is None and isinstance(usage, dict):
            total = usage.get("total_tokens")
        try:
            return int(total) if total is not None else None
        except TypeError, ValueError:
            return None
