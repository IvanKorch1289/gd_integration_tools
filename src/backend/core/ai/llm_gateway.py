"""LLM gateway facade для extensions (S44 W1, ADR-0248 follow-up).

Single entry-point для LLM gateway access из extensions. Re-export canonical
``core.ai.gateway.client.LiteLLMGateway`` + ``get_litellm_gateway`` factory.

Использование в extensions::

    from src.backend.core.ai.llm_gateway import get_litellm_gateway

    gateway = get_litellm_gateway()
    response = await gateway.acompletion(model="...", messages=[...])

Layer policy: extensions → only core. Этот facade — единственный
разрешённый путь.

Волна 33 (LAYERS, инверсия): реализация перенесена из
``services.ai.gateway.client`` в core — ядро больше не зависит от слоя
services. Публичный путь ``src.backend.services.ai.gateway.client``
сохранён re-export шимом.

S44 W1 sprint goal: закрыть extensions violation в
``extensions/osint_agent/functions/osint_workflow.py:292``.
"""

from __future__ import annotations

from src.backend.core.ai.gateway.client import LiteLLMGateway, get_litellm_gateway

__all__ = ("LiteLLMGateway", "get_litellm_gateway")
