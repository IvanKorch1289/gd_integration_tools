"""Per-tenant guardrails clients (Sprint 11 K1 W2).

LLM Guard (self-hosted) — primary scanner (S35 W1, replaces Rebuff/Lakera external APIs).
Lakera Guard + Rebuff — deprecated, kept for backward-compat (external API calls).

LLM Guard scanners: PromptInjection, Toxicity, Anonymize, Sensitive, BanTopics, EncodedKeywords.
No external API calls — CPU-based, MIT licensed.
"""

from src.backend.services.ai.guardrails.lakera_client import LakeraClient, LakeraResult
from src.backend.core.ai.guardrails.llm_guard_client import (
    LLMGuardClient,
    LLMGuardResult,
)
from src.backend.services.ai.guardrails.rebuff_client import RebuffClient, RebuffResult
from src.backend.services.ai.guardrails.tenant_config import (
    GuardrailsConfig,
    GuardrailsThresholds,
)

__all__ = (
    "GuardrailsConfig",
    "GuardrailsThresholds",
    "LLMGuardClient",
    "LLMGuardResult",
    "LakeraClient",
    "LakeraResult",
    "RebuffClient",
    "RebuffResult",
)
