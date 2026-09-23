"""Сервис rule-engine ruleset registry (Wave [wave:s8/k3-rule-engine-finale]).

Public API:
    * :class:`RuleEngineRegistry` — кэш-обёртка над
      :class:`RuleEngineRepository` с опциональным hot-reload
      (feature flag ``rule_engine_hot_reload``).
"""

from __future__ import annotations

from src.backend.services.integrations.rule_engine.registry import (
    RuleEngineRegistry,
    RulesetCacheEntry,
)

__all__ = ("RuleEngineRegistry", "RulesetCacheEntry")
