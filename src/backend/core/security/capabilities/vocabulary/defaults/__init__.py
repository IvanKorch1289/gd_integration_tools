"""Defaults package — composition root + sub-modules (S50 M2-#5 split).

Извлечено из defaults.py (single-file 545 LOC → sub-package):
- base.py — base capabilities (db, net, fs, mq, cache, workflow, llm)
- ai_rag.py — Sprint 11 AI/RAG Completion
- ai_safety.py — Sprint 24 AI Safety Hardening (ADR-NEW-16/17/18)
- ai_platform.py — Sprint 25-27 AI Platform (ADR-NEW-19/20/21/22/23)

build_default_vocabulary остаётся composition root.
"""

from __future__ import annotations

from src.backend.core.security.capabilities.vocabulary.vocabulary import (
    CapabilityVocabulary,
)

from src.backend.core.security.capabilities.vocabulary.defaults import (
    ai_platform,
    ai_rag,
    ai_safety,
    base,
)


def build_default_vocabulary() -> CapabilityVocabulary:
    """Собирает CapabilityVocabulary с v0-каталогом из ADR-044.

    S50 M2-#5 swarm audit: composition root. Вызывает 4 sub-module register()
    функции (base, ai_rag, ai_safety, ai_platform).

    S50 Sprint D fix: убраны dead-code matcher variables (dot_glob, path_glob,
    cache_glob, exact, uri) — они создавались, но НЕ передавались в base.register()
    (base.py создаёт свои matchers внутри). F841 от ruff.
    """
    vocab = CapabilityVocabulary()

    base.register(vocab)
    ai_rag.register(vocab)
    ai_safety.register(vocab)
    ai_platform.register(vocab)

    return vocab


__all__ = ("build_default_vocabulary",)