"""Guardrails — safety runtime для AI-агентов.

Содержит:
    * LlamaGuardRuntime — модерация через Llama Guard (GGUF / llama.cpp).

.. note::
    ``LLMGuardClient`` был удалён 2026-07-16: upstream ``protectai/llm-guard``
    архивирован 2026-07-09 (см. ``research/agent-framework/REPORT.md`` F4.1).
    Используйте ``LlamaGuardRuntime`` или ``LakeraClient`` как замену.
"""

from __future__ import annotations as annotations

from src.backend.core.ai.guardrails.llamaguard import (  # noqa: F401 — re-export
    GuardResult,
    LlamaGuardRuntime,
)

__all__ = ("GuardResult", "LlamaGuardRuntime")
