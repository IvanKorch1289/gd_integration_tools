"""Guardrails — safety runtime для AI-агентов.

Содержит:
    * LlamaGuardRuntime — модерация через Llama Guard (GGUF / llama.cpp).
"""

from __future__ import annotations

from src.backend.core.ai.guardrails.llamaguard import GuardResult, LlamaGuardRuntime

__all__ = ("LlamaGuardRuntime", "GuardResult")
