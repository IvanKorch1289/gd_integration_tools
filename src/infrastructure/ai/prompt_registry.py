"""Prompt registry — версионирование промптов + A/B + feature flags.

Используется AI-агентами для получения актуального шаблона промпта
без hard-codeа. Поддерживает несколько версий для одного ключа с
указанием веса для A/B-routing.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

__all__ = ("PromptVersion", "PromptRegistry")


@dataclass(slots=True)
class PromptVersion:
    key: str
    version: str
    template: str
    weight: float = 1.0  # A/B traffic share
    enabled: bool = True


class PromptRegistry:
    """In-memory registry с weighted routing."""

    def __init__(self) -> None:
        self._items: dict[str, list[PromptVersion]] = {}

    def register(self, version: PromptVersion) -> None:
        self._items.setdefault(version.key, []).append(version)

    def get(self, key: str) -> PromptVersion:
        candidates = [v for v in self._items.get(key, []) if v.enabled]
        if not candidates:
            raise KeyError(f"Prompt not found: {key}")
        if len(candidates) == 1:
            return candidates[0]
        total = sum(c.weight for c in candidates) or 1.0
        r = random.random() * total
        acc = 0.0
        for c in candidates:
            acc += c.weight
            if r <= acc:
                return c
        return candidates[-1]

    def list_keys(self) -> list[str]:
        return sorted(self._items.keys())


registry = PromptRegistry()
