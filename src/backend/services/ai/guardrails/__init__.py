"""Per-tenant guardrails clients (Sprint 11 K1 W2).

Lakera Guard + Rebuff — внешние провайдеры prompt-injection / PII detection.
Каждый клиент использует ``core.net.migration_helper.make_http_client`` для
WAF фасада (capability ``ai.guardrails.lakera``/``ai.guardrails.rebuff``).
"""

from src.backend.services.ai.guardrails.lakera_client import (
    LakeraClient,
    LakeraResult,
)
from src.backend.services.ai.guardrails.rebuff_client import (
    RebuffClient,
    RebuffResult,
)
from src.backend.services.ai.guardrails.tenant_config import (
    GuardrailsConfig,
    GuardrailsThresholds,
)

__all__ = (
    "GuardrailsConfig",
    "GuardrailsThresholds",
    "LakeraClient",
    "LakeraResult",
    "RebuffClient",
    "RebuffResult",
)
