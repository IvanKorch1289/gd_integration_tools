"""AI / RPA / Banking-AI миксин для ``RouteBuilder`` (S52 W1 closure).

S51 W1: AILlMMixin (18 AI/LLM methods).
S51 W2: RPAMixin (20 RPA methods).
S52 W1: TextOpsMixin (5) + SystemOpsMixin (7) + BankingScriptsMixin (11) = 23 methods.

All 61 methods now distributed across 5 mixin files.
Stateless: использует ``self._add`` / ``self._add_lazy`` через MRO.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builder import (
        RouteBuilder,  # noqa: F401  # S52 W1: forward ref only
    )

from src.backend.dsl.builders.ai_rpa.ai_llm import AILlMMixin  # S51 W1: MRO
from src.backend.dsl.builders.ai_rpa.banking_scripts import (
    BankingScriptsMixin,  # S52 W1: MRO
)
from src.backend.dsl.builders.ai_rpa.rpa import RPAMixin  # S51 W2: MRO
from src.backend.dsl.builders.ai_rpa.system_ops import SystemOpsMixin  # S52 W1: MRO
from src.backend.dsl.builders.ai_rpa.text_ops import TextOpsMixin  # S52 W1: MRO


class AIRPAMixin(
    BankingScriptsMixin,
    SystemOpsMixin,
    TextOpsMixin,
    RPAMixin,
    AILlMMixin,
):
    """MRO composition: 5 mixins = 18 + 20 + 5 + 7 + 11 = 61 methods."""

    __slots__ = ()
