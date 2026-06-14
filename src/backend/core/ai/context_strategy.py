"""Context strategy: rolling window + map-reduce + hierarchical (gap-ai-8).

Управляет размером контекста в рамках BudgetSpec.max_tokens_prompt.
Три стратегии:

1. **rolling_window** (default) — keep last N messages that fit budget.
2. **map_reduce** — summarize old messages into a single condensation,
   keep recent as-is.
3. **hierarchical** — progressively condense older message groups
   (recent → summary → older summary → …).

Вход: список ``ConversationMessage`` + budget.
Выход: отфильтрованный/модифицированный список.

Используется в :meth:`AIGateway._render_prompt` (gateway.py Шаг 5).
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from src.backend.core.logging import get_logger

__all__ = (
    "ContextMessage",
    "ContextStrategy",
    "HierarchicalStrategy",
    "MapReduceStrategy",
    "RollingWindowStrategy",
    "TokenBudget",
    "get_context_strategy",
)

logger = get_logger("core.ai.context_strategy")


class ContextStrategyType(StrEnum):
    """Available context management strategies."""

    ROLLING_WINDOW = "rolling_window"
    MAP_REDUCE = "map_reduce"
    HIERARCHICAL = "hierarchical"


@dataclass(slots=True, frozen=True)
class ContextMessage:
    """Один message в conversation history.

    Attributes:
        role: Message role (user / assistant / system).
        content: Текст сообщения.
        token_count: Предвычисленный размер (если known).
    """

    role: str
    content: str
    token_count: int | None = None


@dataclass
class TokenBudget:
    """Token budget для context truncation.

    Attributes:
        limit: Максимальное число токенов (from BudgetSpec.max_tokens_prompt).
        system_tokens: Токены system prompt (reserved, not truncated).
        reserve_tokens: Резерв для текущего user message.
    """

    limit: int
    system_tokens: int = 0
    reserve_tokens: int = 0

    @property
    def available(self) -> int:
        """Токены доступные для history."""
        return max(0, self.limit - self.system_tokens - self.reserve_tokens)


class ContextStrategy(ABC):
    """Abstract base для context strategies."""

    @abstractmethod
    def apply(
        self,
        messages: list[ContextMessage],
        budget: TokenBudget,
        *,
        count_tokens: Any = None,
    ) -> list[ContextMessage]:
        """Apply strategy to messages within budget.

        Args:
            messages: Conversation history (включая system + recent user).
            budget: TokenBudget с лимитами.
            count_tokens: Callback ``(str) -> int`` для подсчёта токенов
                (e.g. tiktoken). Если None — используется len(content).

        Returns:
            Модифицированный список messages для передачи в LLM.
        """
        ...


def _default_count_tokens(text: str) -> int:
    """Rough estimate: ~4 chars per token (tiktoken approximation)."""
    return max(1, len(text) // 4)


class RollingWindowStrategy(ContextStrategy):
    """Keep the most recent N messages that fit within budget.

    System message preserved if present. Messages beyond budget are
    dropped from the oldest side.
    """

    def apply(
        self,
        messages: list[ContextMessage],
        budget: TokenBudget,
        *,
        count_tokens: Any = None,
    ) -> list[ContextMessage]:
        """Применить стратегию усечения контекста к ``messages``.

        Конкретная стратегия (rolling window / map-reduce / hierarchical)
        определена в наследнике. Все реализации возвращают новый список
        сообщений, вписывающийся в ``budget``.

        Args:
            messages: Входной список сообщений (свежие — в конце).
            budget: Лимит токенов для контекста.
            count_tokens: Опциональный callable ``list[ContextMessage] -> int``.
                Если не передан, используется эвристика (4 символа ≈ 1 токен).

        Returns:
            Новый список сообщений, вписывающийся в бюджет. ``[]`` если
            входной список пуст.
        """
        if not messages:
            return []

        counter = count_tokens or _default_count_tokens

        # Ensure system message is always first if present
        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        # Compute token sizes
        def _tokens(m: ContextMessage) -> int:
            return m.token_count if m.token_count is not None else counter(m.content)

        result: list[ContextMessage] = list(system_msgs)
        available = budget.available - sum(_tokens(m) for m in system_msgs)

        # Walk backwards from most recent
        for msg in reversed(non_system):
            t = _tokens(msg)
            if t <= available:
                result.insert(len(system_msgs), msg)
                available -= t
            else:
                # Try to fit a truncation notice
                break

        if len(result) < len(messages):
            logger.debug(
                "RollingWindow: dropped %d messages, kept %d (budget=%d)",
                len(messages) - len(result),
                len(result),
                budget.limit,
            )

        return result


class MapReduceStrategy(ContextStrategy):
    """Map-reduce: summarize old messages, keep recent as-is.

    Old messages (those that don't fit budget) are collapsed into a
    single ``[condensed history]`` assistant message. Recent messages
    are kept verbatim.
    """

    def __init__(self, *, recent_count: int = 10) -> None:
        """Initialize.

        Args:
            recent_count: Сколько самых свежих non-system сообщений
                оставить без изменений.
        """
        self._recent_count = recent_count

    def apply(
        self,
        messages: list[ContextMessage],
        budget: TokenBudget,
        *,
        count_tokens: Any = None,
    ) -> list[ContextMessage]:
        """Применить стратегию усечения контекста к ``messages``.

        Конкретная стратегия (rolling window / map-reduce / hierarchical)
        определена в наследнике. Все реализации возвращают новый список
        сообщений, вписывающийся в ``budget``.

        Args:
            messages: Входной список сообщений (свежие — в конце).
            budget: Лимит токенов для контекста.
            count_tokens: Опциональный callable ``list[ContextMessage] -> int``.
                Если не передан, используется эвристика (4 символа ≈ 1 токен).

        Returns:
            Новый список сообщений, вписывающийся в бюджет. ``[]`` если
            входной список пуст.
        """
        if not messages:
            return []

        counter = count_tokens or _default_count_tokens

        def _tokens(m: ContextMessage) -> int:
            return m.token_count if m.token_count is not None else counter(m.content)

        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        available = budget.available - sum(_tokens(m) for m in system_msgs)

        # Keep recent N messages that fit
        recent: list[ContextMessage] = []
        older: list[ContextMessage] = []

        for msg in reversed(non_system):
            t = _tokens(msg)
            if t <= available and len(recent) < self._recent_count:
                recent.insert(0, msg)
                available -= t
            else:
                older.insert(0, msg)

        result: list[ContextMessage] = list(system_msgs)

        if older:
            # Condense older messages into a summary placeholder
            older_text = "\n".join(
                f"[{m.role}]: {m.content[:200]}{'...' if len(m.content) > 200 else ''}"
                for m in older
            )
            condensation = ContextMessage(
                role="system",
                content=(
                    f"[Prior conversation summarized ({len(older)} messages): "
                    f"{older_text[:1000]}{'...' if len(older_text) > 1000 else ''}]"
                ),
            )
            t = _tokens(condensation)
            if t <= available:
                result.append(condensation)
            else:
                logger.debug(
                    "MapReduce: condensation %d tokens exceeds remaining %d",
                    t,
                    available,
                )

        result.extend(recent)
        return result


class HierarchicalStrategy(ContextStrategy):
    """Hierarchical: progressively condense older message groups.

    Recent messages kept verbatim. Older groups are progressively
    condensed: each level halves the group size.
    """

    def __init__(self, *, levels: int = 3, base_group_size: int = 20) -> None:
        """Initialize.

        Args:
            levels: Число уровней иерархии (default 3: recent + 2 summary levels).
            base_group_size: Размер группы на level=0 (default 20 messages).
        """
        self._levels = levels
        self._base_group_size = base_group_size

    def apply(
        self,
        messages: list[ContextMessage],
        budget: TokenBudget,
        *,
        count_tokens: Any = None,
    ) -> list[ContextMessage]:
        """Применить стратегию усечения контекста к ``messages``.

        Конкретная стратегия (rolling window / map-reduce / hierarchical)
        определена в наследнике. Все реализации возвращают новый список
        сообщений, вписывающийся в ``budget``.

        Args:
            messages: Входной список сообщений (свежие — в конце).
            budget: Лимит токенов для контекста.
            count_tokens: Опциональный callable ``list[ContextMessage] -> int``.
                Если не передан, используется эвристика (4 символа ≈ 1 токен).

        Returns:
            Новый список сообщений, вписывающийся в бюджет. ``[]`` если
            входной список пуст.
        """
        if not messages:
            return []

        counter = count_tokens or _default_count_tokens

        def _tokens(m: ContextMessage) -> int:
            return m.token_count if m.token_count is not None else counter(m.content)

        system_msgs = [m for m in messages if m.role == "system"]
        non_system = [m for m in messages if m.role != "system"]

        available = budget.available - sum(_tokens(m) for m in system_msgs)

        # Level 0: most recent messages (verbatim)
        level0_size = min(self._base_group_size, len(non_system))
        level0 = non_system[-level0_size:]
        older = non_system[:-level0_size] if level0_size < len(non_system) else []

        result: list[ContextMessage] = list(system_msgs)

        # Build hierarchical summaries
        current_group = older
        for level in range(self._levels):
            if not current_group:
                break

            group_size = max(1, self._base_group_size // (2**level))
            # Summarize this group
            group_text = "\n".join(
                f"[{m.role}]: {m.content[:150]}{'...' if len(m.content) > 150 else ''}"
                for m in current_group[-group_size:]
            )
            condensation = ContextMessage(
                role="system",
                content=f"[Earlier ({len(current_group)} msgs, level {level}): {group_text[:500]}{'...' if len(group_text) > 500 else ''}]",
            )
            t = _tokens(condensation)

            if t <= available:
                result.append(condensation)
                available -= t
                # Move older messages to next level
                current_group = (
                    current_group[:-group_size]
                    if len(current_group) > group_size
                    else []
                )
            else:
                logger.debug(
                    "Hierarchical level %d: summary %d tokens exceeds remaining %d",
                    level,
                    t,
                    available,
                )
                break

        result.extend(level0)
        return result


_STRATEGIES: dict[ContextStrategyType, type[ContextStrategy]] = {
    ContextStrategyType.ROLLING_WINDOW: RollingWindowStrategy,
    ContextStrategyType.MAP_REDUCE: MapReduceStrategy,
    ContextStrategyType.HIERARCHICAL: HierarchicalStrategy,
}


def get_context_strategy(
    strategy: ContextStrategyType | str = ContextStrategyType.ROLLING_WINDOW,
    **kwargs: Any,
) -> ContextStrategy:
    """Factory: получить strategy instance по типу."""
    if isinstance(strategy, str):
        strategy = ContextStrategyType(strategy)
    cls = _STRATEGIES.get(strategy)
    if cls is None:
        logger.warning("Unknown strategy %s, falling back to rolling_window", strategy)
        cls = RollingWindowStrategy
    return cls(**kwargs)
