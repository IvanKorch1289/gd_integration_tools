"""Per-tenant guardrails clients (Sprint 11 K1 W2).

.. note::
    LLM Guard (S35 W1) and Rebuff (Sprint 11) clients were removed 2026-07-16
    after both upstream libraries were archived by their maintainers.
    See ``research/agent-framework/REPORT.md`` F4.1, F4.2.

Lakera Guard (external API) and NeMo Guard are the remaining providers.
NeMo is self-hosted; Lakera remains the only third-party API integration.
"""

from src.backend.services.ai.guardrails.lakera_client import LakeraClient, LakeraResult
from src.backend.services.ai.guardrails.tenant_config import (
    GuardrailsConfig,
    GuardrailsThresholds,
)

__all__ = ("GuardrailsConfig", "GuardrailsThresholds", "LakeraClient", "LakeraResult")
