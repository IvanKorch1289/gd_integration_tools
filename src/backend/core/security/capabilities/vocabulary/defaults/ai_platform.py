"""AI Platform capabilities registration (S50 M2-#5 split).

Извлечено из defaults.py. Sprint 25-27 AI Platform Layer
(ADR-NEW-19/20/21/22/23, ADR-0070).
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import GlobScopeMatcher
from src.backend.core.security.capabilities.vocabulary.models import CapabilityDef
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)


def register(vocab: CapabilityVocabulary) -> None:
    """Register Sprint 25-27 AI Platform Layer capabilities."""
    dot_glob = GlobScopeMatcher()

    vocab.register(
        CapabilityDef(
            name="ai.invoke",
            matcher=dot_glob,
            description=(
                "Вызов LLM через единую точку входа AIGateway (ADR-NEW-19). "
                "Проверяется на каждый AIGateway.invoke(request.workflow_id); "
                "scope = workflow_id pattern или '*' (S25 W1)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.policy.read",
            matcher=dot_glob,
            description=(
                "Чтение AIPolicySpec из ai_policies/*.policy.yaml через "
                "PolicyResolver (ADR-NEW-20); scope = policy-name pattern "
                "или '*' (S25 W2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.tokenize.reversible",
            matcher=dot_glob,
            description=(
                "Reversible PII-токенизация через PIITokenizer (Presidio + "
                "AES-GCM TokenRegistry); обязательна для unmask round-trip "
                "(ADR-NEW-21). scope = domain-id (banking, hr, medical) или '*' "
                "(S25 W4)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="mcp.gateway.invoke",
            matcher=dot_glob,
            description=(
                "Вызов tool через MCPGateway namespace (credit/analytics/"
                "system) с auth + WAF (ADR-NEW-23); scope = namespace-name "
                "или '*' (S27 W4)."
            ),
        )
    )
    # Per-namespace capabilities (ADR-0070 §1, S27 W4)
    for _ns_name in ("credit", "analytics", "system"):
        vocab.register(
            CapabilityDef(
                name=f"mcp.gateway.invoke.{_ns_name}",
                matcher=dot_glob,
                description=(
                    f"Вызов tool в namespace '{_ns_name}' через MCPGateway "
                    f"(ADR-0070, S27 W4); scope = tool-name или '*'."
                ),
            )
        )
    vocab.register(
        CapabilityDef(
            name="skill.invoke",
            matcher=dot_glob,
            description=(
                "Вызов AI skill через SkillRegistry (ADR-NEW-22, S26 W5); "
                "scope = skill-id pattern (``credit.score.calculate``, "
                "``credit.*``) или '*' (S27 W3 DSL .skill_invoke())."
            ),
        )
    )
