"""AI/RAG capabilities registration (S50 M2-#5 split).

Извлечено из defaults.py. Sprint 11 AI/RAG Completion.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
)
from src.backend.core.security.capabilities.vocabulary.models import (
    CapabilityDef,
)
from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)


def register(vocab: CapabilityVocabulary) -> None:
    """Register Sprint 11 AI/RAG Completion capabilities."""
    exact = ExactAliasMatcher()
    dot_glob = GlobScopeMatcher()

    vocab.register(
        CapabilityDef(
            name="ai.rag.pii_redaction",
            matcher=exact,
            description=(
                "Применение PII-маскера к augment_result.documents[*].content "
                "в RAG retrieval pipeline (S11 K1 W1)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrails.lakera",
            matcher=dot_glob,
            description=(
                "Вызов Lakera Guard prompt-injection / PII detector. "
                "scope = '*' или конкретный provider-id (S11 K1 W2)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrails.nemo",
            matcher=dot_glob,
            description=(
                "Вызов NeMo Colang self-check guard (S172, replaces Rebuff). "
                "scope = '*' или provider-id. "
                "research/agent-framework/REPORT.md F4.2."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.guardrails.rebuff",
            matcher=dot_glob,
            description=(
                "[DEPRECATED S172] Вызов Rebuff prompt-injection detector — "
                "upstream archived 2026; capability сохранён для backward-compat "
                "grants in existing roles. "
                "Migrate to ai.guardrails.nemo. "
                "research/agent-framework/REPORT.md F4.2."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.model_registry.read",
            matcher=dot_glob,
            description=(
                "Чтение из AI Model Registry (MLflow + HF Hub composite); "
                "scope = backend-id или '*' (S11 K4 W6)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.model_registry.write",
            matcher=dot_glob,
            description=(
                "Запись/promote в AI Model Registry. "
                "scope = backend-id или '*' (S11 K4 W6)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.feedback.train",
            matcher=exact,
            description=(
                "Запуск DSPy training-loop по labeled feedback "
                "+ публикация prompt-version (S11 K4 W5)."
            ),
        )
    )
    vocab.register(
        CapabilityDef(
            name="ai.route.optimize",
            matcher=dot_glob,
            description=(
                "AI-анализ route-метрик + генерация PR markdown "
                "(S11 K4 W7); scope = route-name или '*'."
            ),
        )
    )