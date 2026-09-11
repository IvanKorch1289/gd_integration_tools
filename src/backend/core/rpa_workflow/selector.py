"""Selector resilience — priority/fallback chains для RPA."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

__all__ = ("Selector", "SelectorChain", "SelectorStrategy", "SelectorType")


class SelectorType(str, enum.Enum):
    """Тип selector'а."""

    CSS = "css"
    XPATH = "xpath"
    ARIA = "aria"
    TEXT = "text"
    DATA_TESTID = "data-testid"
    ROLE = "role"


class SelectorStrategy(str, enum.Enum):
    """Стратегия fallback."""

    FIRST = "first"  # use only first selector
    FALLBACK = "fallback"  # try next if previous fails
    ALL = "all"  # use all (multi-binding)


@dataclass(slots=True)
class Selector:
    """Single selector."""

    selector_type: SelectorType
    value: str
    description: str = ""


@dataclass(slots=True)
class SelectorChain:
    """Priority-ordered chain of selectors (first tries priority 0)."""

    selectors: list[Selector] = field(default_factory=list)
    strategy: SelectorStrategy = SelectorStrategy.FALLBACK

    def resolve(self, attempt: int = 0) -> Selector | None:
        """Resolve selector по attempt number.

        Args:
            attempt: 0 = first selector, 1 = fallback, etc.

        Returns:
            Selector to use или None если all failed.
        """
        if not self.selectors:
            return None
        if self.strategy == SelectorStrategy.FIRST:
            return self.selectors[0]
        if attempt < len(self.selectors):
            return self.selectors[attempt]
        return None

    def attempts_count(self) -> int:
        """Сколько попыток до окончательного fail."""
        if self.strategy == SelectorStrategy.FIRST:
            return 1
        return len(self.selectors)
