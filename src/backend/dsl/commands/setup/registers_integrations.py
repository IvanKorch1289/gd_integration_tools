from __future__ import annotations
"""S66 W2 — registers_integrations.py part of setup.py decomp.

integration registrations (AI, analytics, search, RAG, etc.).

Functions: _register_ai, _register_analytics_clickhouse, _register_search_elasticsearch, _register_notebooks_wave_9_1, _register_rag_vector_db_llm, _register_agent_memory, _register_web_search_perplexity_tavily, _register_anomaly_detection.
"""

from collections.abc import Callable

from src.backend.dsl.commands.registry import ActionHandlerSpec, action_handler_registry





def _register_ai() -> None:
    from src.backend.services.ai.ai_agent import get_ai_agent_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="ai.search_web",
                service_getter=get_ai_agent_service,
                service_method="search_web",
            ),
            ActionHandlerSpec(
                action="ai.parse_webpage",
                service_getter=get_ai_agent_service,
                service_method="parse_webpage",
            ),
            ActionHandlerSpec(
                action="ai.chat",
                service_getter=get_ai_agent_service,
                service_method="chat",
            ),
            ActionHandlerSpec(
                action="ai.run_agent",
                service_getter=get_ai_agent_service,
                service_method="run_agent",
            ),
        ]
    )



def _register_analytics_clickhouse() -> None:

    from src.backend.services.ops.analytics import get_analytics_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="analytics.insert_event",
                service_getter=get_analytics_service,
                service_method="insert_event",
            ),
            ActionHandlerSpec(
                action="analytics.insert_batch",
                service_getter=get_analytics_service,
                service_method="insert_batch",
            ),
            ActionHandlerSpec(
                action="analytics.query",
                service_getter=get_analytics_service,
                service_method="query",
            ),
            ActionHandlerSpec(
                action="analytics.count",
                service_getter=get_analytics_service,
                service_method="count",
            ),
            ActionHandlerSpec(
                action="analytics.aggregate",
                service_getter=get_analytics_service,
                service_method="aggregate",
            ),
        ]
    )



def _register_search_elasticsearch() -> None:

    from src.backend.services.io.search import get_search_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="search.index_document",
                service_getter=get_search_service,
                service_method="index_document",
            ),
            ActionHandlerSpec(
                action="search.bulk_index",
                service_getter=get_search_service,
                service_method="bulk_index",
            ),
            ActionHandlerSpec(
                action="search.query",
                service_getter=get_search_service,
                service_method="search",
            ),
            ActionHandlerSpec(
                action="search.aggregate",
                service_getter=get_search_service,
                service_method="aggregate",
            ),
            ActionHandlerSpec(
                action="search.delete_document",
                service_getter=get_search_service,
                service_method="delete_document",
            ),
        ]
    )



def _register_notebooks_wave_9_1() -> None:

    from src.backend.services.notebooks import get_notebook_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="notebooks.create",
                service_getter=get_notebook_service,
                service_method="create",
            ),
            ActionHandlerSpec(
                action="notebooks.get",
                service_getter=get_notebook_service,
                service_method="get",
            ),
            ActionHandlerSpec(
                action="notebooks.update_content",
                service_getter=get_notebook_service,
                service_method="update_content",
            ),
            ActionHandlerSpec(
                action="notebooks.restore_version",
                service_getter=get_notebook_service,
                service_method="restore_version",
            ),
            ActionHandlerSpec(
                action="notebooks.list",
                service_getter=get_notebook_service,
                service_method="list_all",
            ),
            ActionHandlerSpec(
                action="notebooks.delete",
                service_getter=get_notebook_service,
                service_method="delete",
            ),
        ]
    )



def _register_rag_vector_db_llm() -> None:

    from src.backend.services.ai.rag_service import get_rag_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="rag.ingest",
                service_getter=get_rag_service,
                service_method="ingest",
            ),
            ActionHandlerSpec(
                action="rag.search",
                service_getter=get_rag_service,
                service_method="search",
            ),
            ActionHandlerSpec(
                action="rag.augment_prompt",
                service_getter=get_rag_service,
                service_method="augment_prompt",
            ),
            ActionHandlerSpec(
                action="rag.delete",
                service_getter=get_rag_service,
                service_method="delete",
            ),
            ActionHandlerSpec(
                action="rag.count",
                service_getter=get_rag_service,
                service_method="count",
            ),
        ]
    )



def _register_agent_memory() -> None:

    from src.backend.services.ai.agent_memory import get_agent_memory_service

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="agent_memory.load",
                service_getter=get_agent_memory_service,
                service_method="load_memory",
            ),
            ActionHandlerSpec(
                action="agent_memory.save",
                service_getter=get_agent_memory_service,
                service_method="save_memory",
            ),
            ActionHandlerSpec(
                action="agent_memory.add_message",
                service_getter=get_agent_memory_service,
                service_method="add_message",
            ),
            ActionHandlerSpec(
                action="agent_memory.get_conversation",
                service_getter=get_agent_memory_service,
                service_method="get_conversation",
            ),
            ActionHandlerSpec(
                action="agent_memory.clear",
                service_getter=get_agent_memory_service,
                service_method="clear_conversation",
            ),
            ActionHandlerSpec(
                action="agent_memory.set_fact",
                service_getter=get_agent_memory_service,
                service_method="set_fact",
            ),
            ActionHandlerSpec(
                action="agent_memory.get_facts",
                service_getter=get_agent_memory_service,
                service_method="get_facts",
            ),
        ]
    )



def _register_web_search_perplexity_tavily() -> None:

    from src.backend.infrastructure.clients.external.search_providers import (
        get_web_search_service,
    )

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="web_search.query",
                service_getter=get_web_search_service,
                service_method="query",
            ),
            ActionHandlerSpec(
                action="web_search.deep_research",
                service_getter=get_web_search_service,
                service_method="deep_research",
            ),
        ]
    )



def _register_anomaly_detection() -> None:

    from src.backend.services.ops.anomaly_detector import get_anomaly_detector

    action_handler_registry.register_many(
        [
            ActionHandlerSpec(
                action="anomaly.observe",
                service_getter=get_anomaly_detector,
                service_method="observe",
            ),
            ActionHandlerSpec(
                action="anomaly.stats",
                service_getter=get_anomaly_detector,
                service_method="get_stats",
            ),
            ActionHandlerSpec(
                action="anomaly.list_metrics",
                service_getter=get_anomaly_detector,
                service_method="list_metrics",
            ),
        ]
    )



