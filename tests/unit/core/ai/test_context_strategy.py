"""Smoke-тесты для HierarchicalStrategy (Round 44 R44-5).

HierarchicalStrategy зарегистрирована в ``_STRATEGIES`` dict
(context_strategy.py:383) и используется через ``ContextStrategyType.HIERARCHICAL``,
но до Round 44 не было ни одного теста.

Тесты проверяют базовые контракты (smoke-level):
- ``HierarchicalStrategy().apply(messages, budget)`` возвращает list[Message]
- ``get_context_strategy(ContextStrategyType.HIERARCHICAL)`` возвращает
  HierarchicalStrategy instance.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.core.ai.context_strategy import (
    ContextMessage,
    ContextStrategyType,
    HierarchicalStrategy,
    TokenBudget,
    get_context_strategy,
)


def _msg(idx: int) -> ContextMessage:
    """Helper: создать test message с idx в content."""
    return ContextMessage(role="user" if idx % 2 == 0 else "assistant", content=f"message {idx}")


def _budget(limit: int = 1000) -> TokenBudget:
    """Helper: TokenBudget с заданным лимитом."""
    return TokenBudget(limit=limit)


def test_hierarchical_strategy_apply_smoke() -> None:
    """Round 44 R44-5: ``HierarchicalStrategy().apply(messages, budget)`` возвращает list[ContextMessage].

    Smoke test — проверяем что apply() не падает и возвращает
    непустой список (recent messages kept verbatim + older summarized).
    """
    strategy = HierarchicalStrategy(levels=3, base_group_size=10)
    messages = [_msg(i) for i in range(50)]
    result = strategy.apply(messages, budget=_budget(limit=1000))
    assert isinstance(result, list)
    assert len(result) > 0
    # HierarchicalStrategy всегда возвращает как минимум последние сообщения.
    assert len(result) <= len(messages)


def test_hierarchical_strategy_handles_small_input() -> None:
    """Smoke: ``apply()`` с маленьким input (меньше base_group_size)."""
    strategy = HierarchicalStrategy(levels=3, base_group_size=20)
    messages = [_msg(i) for i in range(5)]
    result = strategy.apply(messages, budget=_budget(limit=100))
    assert isinstance(result, list)
    assert len(result) == 5  # все messages сохраняются (input < base_group_size)


def test_hierarchical_strategy_empty_input() -> None:
    """Smoke: ``apply([])`` возвращает пустой список."""
    strategy = HierarchicalStrategy()
    result = strategy.apply([], budget=_budget(limit=100))
    assert result == []


def test_get_context_strategy_returns_hierarchical() -> None:
    """Round 44 R44-5: factory ``get_context_strategy(HIERARCHICAL)`` возвращает HierarchicalStrategy.

    Проверяет регистрацию strategy в ``_STRATEGIES`` dict и
    правильную работу factory function.
    """
    strategy = get_context_strategy(ContextStrategyType.HIERARCHICAL)
    assert isinstance(strategy, HierarchicalStrategy)


def test_get_context_strategy_default_is_rolling_window() -> None:
    """Round 44 R44-5: factory default — ``RollingWindowStrategy``."""
    from src.backend.core.ai.context_strategy import RollingWindowStrategy

    strategy = get_context_strategy()
    assert isinstance(strategy, RollingWindowStrategy)
