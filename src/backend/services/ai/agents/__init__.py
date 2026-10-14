"""Специализированные AI-агенты (Wave 8.7).

Содержит:

* :class:`AnalyticsAgent` — Polars/DuckDB-аналитика;
* :class:`SearchAgent` — RAG + AgentMemory.

Все агенты экспозятся через REST ``POST /api/v1/ai/agents/{name}/invoke``.

Note (2026-10-14 audit-stabilization Proposal 3): ``langgraph_postgres_saver``
был удалён, так как ``langchain_postgres.AsyncPostgresSaver`` не существует
в ``langchain_postgres==0.0.17``. Если checkpoint-функционал потребуется
в будущем, см. git history для восстановления.
"""

from __future__ import annotations

from src.backend.services.ai.agents.analytics_agent import (
    AnalyticsAgent,
    get_analytics_agent,
)
from src.backend.services.ai.agents.search_agent import SearchAgent, get_search_agent

__all__ = (
    "AnalyticsAgent",
    "SearchAgent",
    "get_analytics_agent",
    "get_search_agent",
)
