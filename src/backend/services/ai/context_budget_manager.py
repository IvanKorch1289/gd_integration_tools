"""ContextBudgetManager — token budget management для LLM context windows (Wave S29 K1 W5).

Назначение
----------
Управляет бюджетом токенов в LLM context window через 3 стратегии:

* **rolling** — оставляет последние N токенов, удаляет старые сообщения.
* **map-reduce** — разбивает контекст на chunks, обрабатывает каждый,
  затем объединяет результаты.
* **hierarchical** — summarization старых сообщений через отдельный LLM call
  (condense), оставляя только последние N токенов.

Использование
-------------
::

    from src.backend.services.ai.context_budget_manager import (
        ContextBudgetManager,
        ContextStrategy,
        get_context_budget_manager,
    )

    manager = get_context_budget_manager()
    strategy = manager.get_strategy("rolling")
    trimmed = await strategy.trim(messages, max_tokens=8192)

Регистрация стратегий происходит автоматически при импорте модуля.
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = (
    "ContextBudgetManager",
    "ContextStrategy",
    "ContextStrategyType",
    "HierarchicalStrategy",
    "MapReduceStrategy",
    "RollingStrategy",
    "get_context_budget_manager",
)

logger = get_logger("services.ai.context_budget")


class ContextStrategyType(Enum):
    """Типы стратегий управления контекстом."""

    ROLLING = "rolling"
    MAP_REDUCE = "map_reduce"
    HIERARCHICAL = "hierarchical"


@dataclass(slots=True)
class ContextBudgetResult:
    """Результат применения стратегии."""

    messages: list[dict[str, Any]]
    tokens_used: int
    tokens_remaining: int
    strategy: ContextStrategyType
    dropped_count: int = 0


class ContextStrategy(ABC):
    """Abstract base для стратегий управления контекстом."""

    @property
    @abstractmethod
    def strategy_type(self) -> ContextStrategyType:
        """Return strategy type identifier."""

    @abstractmethod
    async def trim(
        self,
        messages: Sequence[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
    ) -> ContextBudgetResult:
        """Trim messages to fit within token budget.

        Args:
            messages: Список сообщений [{role, content, ...}, ...].
            max_tokens: Максимальное количество токенов.
            model: Модель для подсчёта токенов (опционально).

        Returns:
            ContextBudgetResult с trimmed messages и статистикой.
        """
        ...


class RollingStrategy(ContextStrategy):
    """Rolling strategy — оставляет последние N токенов сообщений.

    Простая стратегия: считает токены через tiktoken и оставляет
    только последние сообщения, пока не уложится в бюджет.
    """

    @property
    def strategy_type(self) -> ContextStrategyType:
        return ContextStrategyType.ROLLING

    async def trim(
        self,
        messages: Sequence[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
    ) -> ContextBudgetResult:
        """Rolling trim — keep most recent messages within token budget."""
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken required for RollingStrategy: pip install tiktoken"
            ) from exc

        enc = tiktoken.get_encoding("cl100k_base")
        result_messages: list[dict[str, Any]] = []
        tokens_used = 0
        dropped_count = 0

        # Iterate from newest to oldest
        for msg in reversed(list(messages)):
            content = str(msg.get("content", ""))
            msg_tokens = len(enc.encode(content))

            if tokens_used + msg_tokens <= max_tokens:
                result_messages.insert(0, msg)
                tokens_used += msg_tokens
            else:
                dropped_count += 1

        return ContextBudgetResult(
            messages=result_messages,
            tokens_used=tokens_used,
            tokens_remaining=max_tokens - tokens_used,
            strategy=self.strategy_type,
            dropped_count=dropped_count,
        )


class MapReduceStrategy(ContextStrategy):
    """Map-reduce strategy — разбивает контекст на chunks, обрабатывает отдельно.

    Алгоритм:
    1. Разбивает сообщения на chunks по max_tokens.
    2. Каждый chunk сохраняется отдельно.
    3. Возвращает все chunks с metadata.
    """

    @property
    def strategy_type(self) -> ContextStrategyType:
        return ContextStrategyType.MAP_REDUCE

    async def trim(
        self,
        messages: Sequence[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
    ) -> ContextBudgetResult:
        """Map-reduce trim — разбивает на chunks по token budget."""
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken required for MapReduceStrategy: pip install tiktoken"
            ) from exc

        enc = tiktoken.get_encoding("cl100k_base")
        chunks: list[dict[str, Any]] = []
        current_chunk: list[dict[str, Any]] = []
        current_tokens = 0

        for msg in messages:
            content = str(msg.get("content", ""))
            msg_tokens = len(enc.encode(content))

            if current_tokens + msg_tokens <= max_tokens:
                current_chunk.append(msg)
                current_tokens += msg_tokens
            else:
                if current_chunk:
                    chunks.append(
                        {
                            "role": "system",
                            "content": f"[CHUNK {len(chunks)}] Contains {len(current_chunk)} messages, {current_tokens} tokens",
                            "_chunk_index": len(chunks),
                            "_original_messages": current_chunk,
                        }
                    )
                current_chunk = [msg]
                current_tokens = msg_tokens

        if current_chunk:
            chunks.append(
                {
                    "role": "system",
                    "content": f"[CHUNK {len(chunks)}] Contains {len(current_chunk)} messages, {current_tokens} tokens",
                    "_chunk_index": len(chunks),
                    "_original_messages": current_chunk,
                }
            )

        total_tokens = sum(len(enc.encode(str(c.get("content", "")))) for c in chunks)

        return ContextBudgetResult(
            messages=chunks,
            tokens_used=total_tokens,
            tokens_remaining=max(0, max_tokens - total_tokens),
            strategy=self.strategy_type,
            dropped_count=0,
        )


class HierarchicalStrategy(ContextStrategy):
    """Hierarchical strategy — summarization старых сообщений.

    Алгоритм:
    1. Оставляет последние N токенов как есть.
    2. Старые сообщения группируются и "condense" — summarization через LLM.
    3. Returns condensed summary + recent messages.

    Note: Полная реализация требует LLM для summarization.
    В текущей версии — placeholder с token-based grouping.
    """

    @property
    def strategy_type(self) -> ContextStrategyType:
        return ContextStrategyType.HIERARCHICAL

    async def trim(
        self,
        messages: Sequence[dict[str, Any]],
        max_tokens: int,
        model: str | None = None,
    ) -> ContextBudgetResult:
        """Hierarchical trim — summarize older messages, keep recent."""
        try:
            import tiktoken
        except ImportError as exc:
            raise RuntimeError(
                "tiktoken required for HierarchicalStrategy: pip install tiktoken"
            ) from exc

        enc = tiktoken.get_encoding("cl100k_base")

        # Keep recent messages until we fit in budget
        recent: list[dict[str, Any]] = []
        summary_parts: list[str] = []
        tokens_recent = 0
        tokens_summary = 0

        # Process from newest to oldest
        for msg in reversed(list(messages)):
            content = str(msg.get("content", ""))
            msg_tokens = len(enc.encode(content))

            if tokens_recent + msg_tokens <= max_tokens:
                recent.insert(0, msg)
                tokens_recent += msg_tokens
            else:
                # Summarize this message (placeholder)
                role = msg.get("role", "unknown")
                summary_parts.insert(
                    0,
                    f"[Earlier {role}: {content[:100]}...]"
                    if len(content) > 100
                    else f"[Earlier {role}: {content}]",
                )
                tokens_summary += msg_tokens

        result: list[dict[str, Any]] = []
        if summary_parts:
            result.append(
                {
                    "role": "system",
                    "content": "Previous conversation summary:\n"
                    + "\n".join(summary_parts),
                    "_is_summary": True,
                }
            )
            tokens_summary = len(enc.encode(result[0]["content"]))

        result.extend(recent)

        return ContextBudgetResult(
            messages=result,
            tokens_used=tokens_recent + tokens_summary,
            tokens_remaining=max_tokens - tokens_recent - tokens_summary,
            strategy=self.strategy_type,
            dropped_count=len(summary_parts),
        )


class ContextBudgetManager:
    """Registry и factory для context management стратегий.

    Регистрирует 3 стратегии по умолчанию:
    * rolling (default)
    * map_reduce
    * hierarchical
    """

    def __init__(self) -> None:
        self._strategies: dict[ContextStrategyType, ContextStrategy] = {
            ContextStrategyType.ROLLING: RollingStrategy(),
            ContextStrategyType.MAP_REDUCE: MapReduceStrategy(),
            ContextStrategyType.HIERARCHICAL: HierarchicalStrategy(),
        }
        self._default_strategy = ContextStrategyType.ROLLING

    def register_strategy(self, strategy: ContextStrategy) -> None:
        """Register a custom strategy."""
        self._strategies[strategy.strategy_type] = strategy

    def get_strategy(self, strategy_type: ContextStrategyType | str) -> ContextStrategy:
        """Get strategy by type.

        Args:
            strategy_type: StrategyType enum or string name.

        Returns:
            ContextStrategy instance.

        Raises:
            KeyError: если стратегия не зарегистрирована.
        """
        if isinstance(strategy_type, str):
            strategy_type = ContextStrategyType(strategy_type)
        return self._strategies[strategy_type]

    @property
    def default_strategy(self) -> ContextStrategy:
        """Default strategy (rolling)."""
        return self._strategies[self._default_strategy]

    def list_strategies(self) -> list[ContextStrategyType]:
        """List registered strategy types."""
        return list(self._strategies.keys())


_instance: ContextBudgetManager | None = None


def get_context_budget_manager() -> ContextBudgetManager:
    """Singleton accessor for ContextBudgetManager."""
    global _instance
    if _instance is None:
        _instance = ContextBudgetManager()
    return _instance
