"""AI Safety capabilities registration (S50 M2-#5 split).

Извлечено из defaults.py. Sprint 24 AI Safety Hardening (ADR-NEW-16/17/18).
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import GlobScopeMatcher
from src.backend.core.security.capabilities.vocabulary.models import (
    CapabilityDef,
)
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)


def register(vocab: CapabilityVocabulary) -> None:
    """Register Sprint 24 AI Safety Hardening capabilities."""
    dot_glob = GlobScopeMatcher()

    vocab.register(
        CapabilityDef(
            name="pii.read",
            matcher=dot_glob,
            description=(
                "Чтение текста через PII-detector pipeline (Presidio + ru NER) "
                "перед маскированием/anonymize; scope = tenant-id или '*' "
                "(S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.write",
            matcher=dot_glob,
            description=(
                "Запись маскированных payload-ов в outbound LLM / RAG / DLQ / "
                "Langfuse traces; scope = tenant-id или '*' (S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="pii.audit",
            matcher=dot_glob,
            description=(
                "Запись audit-event pii.{detected,anonymized,blocked} с tenant_id "
                "+ entity_type + redacted_hash в immutable Postgres audit-sink; "
                "scope = tenant-id или '*' (S24 W1, ADR-NEW-16)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrail.evaluate",
            matcher=dot_glob,
            description=(
                "Вызов defense-in-depth guardrails pipeline "
                "(NeMo Colang input rails + Llama Guard 3 output classifier); "
                "scope = tenant-id или '*' (S24 W2, ADR-NEW-17)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrail.policy_read",
            matcher=dot_glob,
            description=(
                "Чтение per-tenant guardrail policy "
                "(NeMo/LlamaGuard/Lakera enable map) из tenant_config.py; "
                "scope = tenant-id или '*' (S24 W2, ADR-NEW-17, "
                "S172: Rebuff заменён на NeMo, F4.2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.read",
            matcher=dot_glob,
            description=(
                "Чтение из MemoryProtocol (LangGraph Checkpointer / Mem0 / AgentMemory); "
                "namespace = '<tenant_id>:<scope>'; scope = tenant-id или '*' "
                "(S24 W3, ADR-NEW-18)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.write",
            matcher=dot_glob,
            description=(
                "Запись в MemoryProtocol; namespace = '<tenant_id>:<scope>'; "
                "scope = tenant-id или '*' (S24 W3, ADR-NEW-18)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.memory.delete",
            matcher=dot_glob,
            description=(
                "Удаление user-memory из MemoryProtocol (GDPR / 152-ФЗ "
                "user-erasure); scope = tenant-id или '*' (S24 W3, ADR-NEW-18)."
            ),
        )
    )