"""Guardrails — safety runtime для AI-агентов.

.. note::
    ``LLMGuardClient`` был удалён 2026-07-16: upstream ``protectai/llm-guard``
    архивирован 2026-07-09 (см. ``research/agent-framework/REPORT.md`` F4.1).
    ``LlamaGuardRuntime`` объявлен как canonical replacement (см. docstring),
    но соответствующий ``llamaguard.py`` submodule не реализован — на
    момент S47 W32 это TODO (см. S48 W33 retro).

Если ``llamaguard.py`` не существует в этой ревизии — facade остаётся
importable (пустой ``__all__``), но ``GuardResult`` / ``LlamaGuardRuntime``
недоступны до реализации submodule.
"""

from __future__ import annotations

__all__: tuple[str, ...] = ()
