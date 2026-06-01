"""Специализированные AI-агенты (Wave 8.7).

Содержит:

* :class:`AnalyticsAgent` — Polars/DuckDB-аналитика;
* :class:`SearchAgent` — RAG + AgentMemory.

Все агенты экспозятся через REST ``POST /api/v1/ai/agents/{name}/invoke``.
"""

from __future__ import annotations

from src.backend.services.ai.agents.analytics_agent import (
    AnalyticsAgent,
    get_analytics_agent,
)
from src.backend.services.ai.agents.langgraph_postgres_saver import (
    LangGraphPostgresSaverUnavailable,
    LangGraphPostgresSaverWrapper,
    get_langgraph_postgres_saver,
)
from src.backend.services.ai.agents.search_agent import SearchAgent, get_search_agent

__all__ = (
    "AnalyticsAgent",
    "LangGraphPostgresSaverUnavailable",
    "LangGraphPostgresSaverWrapper",
    "SearchAgent",
    "get_analytics_agent",
    "get_langgraph_postgres_saver",
    "get_search_agent",
)
