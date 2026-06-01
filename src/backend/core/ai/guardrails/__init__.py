"""Guardrails — safety runtime для AI-агентов.

Содержит:
    * LlamaGuardRuntime — модерация через Llama Guard (GGUF / llama.cpp).
    * LLMGuardClient — self-hosted scanner (PromptInjection, Toxicity, etc.).
"""

from __future__ import annotations

from src.backend.core.ai.guardrails.llamaguard import GuardResult, LlamaGuardRuntime
from src.backend.core.ai.guardrails.llm_guard_client import (
    LLMGuardClient,
    LLMGuardResult,
)

__all__ = ("LlamaGuardRuntime", "GuardResult")
