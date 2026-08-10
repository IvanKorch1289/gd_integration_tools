"""S175 M2.1 (ARC-009): AIGateway facade subpackage.

Архитектура subpackage ``gateway/`` (S175 #8 split completion):
- :mod:`src.backend.core.ai.gateway.gateway` — :class:`AIGateway` facade
  (275 LOC, перенесён из бывшего ``gateway.py`` god-file в Sprint 175).
- :mod:`src.backend.core.ai.gateway.orchestrator.enforced_invoke` —
  9-step pipeline orchestrator (ADR-0071).
- Shared mixins (external, shared с другими AI-компонентами):
  - :mod:`src.backend.core.ai.gateway_orchestrator_mixin` (EnforcedInvokeMixin)
  - :mod:`src.backend.core.ai.gateway_pipeline_mixin` (PipelineStepsMixin)
  - :mod:`src.backend.core.ai.gateway_models` (AIRequest, AIResponse)

S178 (cleanup, parallel WIP): subpackage shadow'ит legacy module →
``from src.backend.core.ai.gateway import AIGateway`` резолвится в
subpackage. Re-export здесь сохраняет backward-compat.

Migration roadmap (post-S175 #8):
- S176 #?: tools/, prompts/, pii/, audit/ sub-modules (PipelineStepsMixin split)
- S176 #?: Sandbox integration → :mod:`src.backend.core.ai.gateway.sandbox`
"""

from __future__ import annotations as annotations

# AIGateway class — перенесён в subpackage (S175 #8 split completion).
from src.backend.core.ai.gateway.gateway import AIGateway  # noqa: F401 — re-export

# AIRequest / AIResponse — external (in gateway_models.py).
from src.backend.core.ai.gateway_models import AIRequest, AIResponse  # noqa: F401 — re-export

# Backward-compat re-export из orchestrator subpackage
from src.backend.core.ai.gateway_orchestrator_mixin import (
    EnforcedInvokeMixin as EnforcedInvokeMixin,
)

__all__ = ("AIGateway", "AIRequest", "AIResponse", "EnforcedInvokeMixin")
